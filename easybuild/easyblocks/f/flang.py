import glob
import os
import shutil
from distutils.version import LooseVersion

from easybuild.easyblocks.c.clang import EB_Clang
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import change_dir, copy_file, mkdir
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext

class EB_Flang(EB_Clang):
    """Support for bootstrapping Flang."""

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Flang."""

        super(EB_Flang, self).__init__(*args, **kwargs)

    def disable_sanitizer_tests(self):
        # Not relevant for flang
        pass

    def extract_step(self):
        """
        Prepare a combined LLVM source tree.  The layout is:
        llvm/             Unpack flang-llvm-*.tar.gz here
          projects/
            openmp/       Unpack openmp-*.tar.xz here
          tools/
            clang/        Unpack flang-flang-driver*.tar.gz here
        """

        # Extract everything into separate directories.
        super(EB_Clang, self).extract_step()

        # Find the full path to the directory that was unpacked from flang-llvm-*.tar.gz
        for tmp in self.src:
            if tmp['name'].startswith("flang-llvm-"):
                self.llvm_src_dir = tmp['finalpath']
                break

        if self.llvm_src_dir is None:
            raise EasyBuildError(
                "Could not determine LLVM source root (LLVM source was not unpacked?)")
        src_dirs = {}

        def find_source_dir(globpatterns, targetdir):
            """Search for directory with globpattern and rename it to targetdir"""
            if not isinstance(globpatterns, list):
                globpatterns = [globpatterns]

            glob_src_dirs = [glob_dir for globpattern in globpatterns for glob_dir in
                             glob.glob(globpattern)]
            if len(glob_src_dirs) != 1:
                raise EasyBuildError(
                    "Failed to find exactly one source directory for pattern %s: %s",
                    globpatterns,
                    glob_src_dirs)
            src_dirs[glob_src_dirs[0]] = targetdir

        if LooseVersion(self.version) >= LooseVersion('3.8'):
            find_source_dir('openmp-*',
                            os.path.join(self.llvm_src_dir, 'projects', 'openmp'))

        find_source_dir('flang-driver-*',
                        os.path.join(self.llvm_src_dir, 'tools', 'clang'))

        # Place the flang code in a separate directory for the build step for after
        # we've built llvm
        self.flang_source_dir = os.path.join(self.llvm_src_dir, '..', 'flang')
        find_source_dir('flang-flang_*', self.flang_source_dir)

        for src in self.src:
            for (dirname, new_path) in src_dirs.items():
                if src['name'].startswith(dirname):
                    old_path = os.path.join(src['finalpath'], dirname)
                    try:
                        shutil.move(old_path, new_path)
                    except IOError as err:
                        raise EasyBuildError("Failed to move %s to %s: %s", old_path,
                                             new_path, err)
                    src['finalpath'] = new_path
                    break

    def build_with_temporary_llvm(self, build_dir, src_dir, parallel=True, additional_options=[]):
        """Build Clang stage N using Clang stage N-1"""

        # Create and enter build directory.
        mkdir(build_dir)
        change_dir(build_dir)

        # Configure.
        CC = os.path.join(self.llvm_obj_dir, 'bin', 'clang')
        CXX = os.path.join(self.llvm_obj_dir, 'bin', 'clang++')
        F90 = os.path.join(self.llvm_obj_dir, 'bin', 'flang')
        LLVM_CONFIG = os.path.join(self.llvm_obj_dir, 'bin', 'llvm-config')
        LIBOMP = os.path.join(self.llvm_obj_dir, 'lib', 'libomp.so')

        options = "-DCMAKE_INSTALL_PREFIX=%s " % self.installdir
        options += "-DCMAKE_C_COMPILER='%s' " % CC
        options += "-DCMAKE_CXX_COMPILER='%s' " % CXX
        options += "-DCMAKE_Fortran_COMPILER='%s' " % F90
        options += "-DLLVM_CONFIG='%s' " % LLVM_CONFIG
        options += "-DFLANG_LIBOMP='%s' " % LIBOMP
        for option in additional_options:
            options += "%s " % option
        options += self.cfg['configopts']

        self.log.info("Configuring")
        run_cmd("cmake %s %s" % (options, src_dir), log_all=True)

        self.log.info("Building")
        if parallel:
            run_cmd("make %s" % self.make_parallel_opts, log_all=True)
        else:
            run_cmd("make", log_all=True)

    def build_step(self):
        # First build llvm and the driver
        super(EB_Flang, self).build_step()
        if self.cfg['bootstrap']:
            self.llvm_obj_dir = self.llvm_obj_dir_stage3
        else:
            self.llvm_obj_dir = self.llvm_obj_dir_stage1

        # Build libpgmath with the temporary llvm
        self.pgmath_build_dir = os.path.join(self.builddir, 'pgmath_obj')
        self.build_with_temporary_llvm(
            self.pgmath_build_dir,
            os.path.join(self.flang_source_dir, 'runtime', 'libpgmath')
            )
        # Build flang with the temporary llvm
        self.flang_build_dir = os.path.join(self.builddir, 'flang_obj')
        shlib_ext = get_shared_lib_ext()
        self.build_with_temporary_llvm(
            self.flang_build_dir,
            self.flang_source_dir,
            parallel=False,  # Can misbehave in parallel
            additional_options=[
                '-DLIBPGMATH=%s' % os.path.join(self.pgmath_build_dir, 'lib', 'libpgmath.%s' % shlib_ext),
                # Supposed to resolve a problem when linking with flang
                '-DCMAKE_BUILD_WITH_INSTALL_RPATH=1',
            ]
        )

    def install_step(self):
        """Install flang binaries and necessary libraries."""
        shlib_ext = get_shared_lib_ext()
        change_dir(self.pgmath_build_dir)
        super(EB_Clang, self).install_step()
        change_dir(self.flang_build_dir)
        super(EB_Clang, self).install_step()
        # Copy over the flang executable from LLVM
        copy_file(
            os.path.join(self.llvm_obj_dir, 'bin', 'flang'),
            os.path.join(self.installdir, 'bin', 'flang'),
        )
        # Also copy over the libomp libraries
        copy_file(
            os.path.join(self.llvm_obj_dir, 'lib', 'libomp.%s' % shlib_ext),
            os.path.join(self.installdir, 'lib'),
        )
        copy_file(
            os.path.join(self.llvm_obj_dir, 'lib', 'libomp.a'),
            os.path.join(self.installdir, 'lib'),
        )

    def sanity_check_step(self):
        """Custom sanity check for Flang."""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                # flang related
                "bin/flang", "bin/flang1", "bin/flang2",
                "include/ieee_arithmetic.mod", "include/ieee_exceptions.mod", "include/ieee_features.mod",
                "include/iso_c_binding.mod", "include/iso_fortran_env.mod",
                "lib/libflang.a", "lib/libflang.%s" % shlib_ext, "lib/libflangmain.a", "lib/libflangrti.a",
                "lib/libflangrti.%s" % shlib_ext,
                # OpenMP related
                "include/omp_lib.h", "include/omp_lib_kinds.mod", "include/omp_lib.mod",
                "lib/libomp.a", "lib/libomp.%s" % shlib_ext, "lib/libompstub.a", "lib/libompstub.%s" % shlib_ext,
                # libpgmath related
                "lib/libpgmath.a", "lib/libpgmath.%s" % shlib_ext],
            'dirs': [],
        }
