##
# Copyright 2013 Dmitri Gribenko
# Copyright 2013-2021 Ghent University
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
Support for building and installing Clang, implemented as an easyblock.

@author: Dmitri Gribenko (National Technical University of Ukraine "KPI")
@author: Ward Poelmans (Ghent University)
@author: Alan O'Cais (Juelich Supercomputing Centre)
"""

import glob
import os
import shutil
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.cmakemake import CMakeMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import run
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import AARCH32, AARCH64, POWER, X86_64
from easybuild.tools.systemtools import get_cpu_architecture, get_os_name, get_os_version, get_shared_lib_ext
from easybuild.tools.environment import setvar

# List of all possible build targets for Clang
CLANG_TARGETS = ["all", "AArch64", "ARM", "CppBackend", "Hexagon", "Mips",
                 "MBlaze", "MSP430", "NVPTX", "PowerPC", "R600", "Sparc",
                 "SystemZ", "X86", "XCore"]

# Mapping of EasyBuild CPU architecture names to list of default LLVM target names
DEFAULT_TARGETS_MAP = {
    AARCH32: ['ARM'],
    AARCH64: ['AArch64'],
    POWER: ['PowerPC'],
    X86_64: ['X86'],
}


class EB_Clang(CMakeMake):
    """Support for bootstrapping Clang."""

    @staticmethod
    def extra_options():
        extra_vars = CMakeMake.extra_options()
        extra_vars.update({
            'assertions': [True, "Enable assertions.  Helps to catch bugs in Clang.", CUSTOM],
            'build_targets': [None, "Build targets for LLVM (host architecture if None). Possible values: " +
                                    ', '.join(CLANG_TARGETS), CUSTOM],
            'bootstrap': [True, "Bootstrap Clang using GCC", CUSTOM],
            'usepolly': [False, "Build Clang with polly", CUSTOM],
            'build_lld': [False, "Build the LLVM lld linker", CUSTOM],
            'default_openmp_runtime': [None, "Default OpenMP runtime for clang (for example, 'libomp')", CUSTOM],
            'enable_rtti': [False, "Enable Clang RTTI", CUSTOM],
            'libcxx': [False, "Build the LLVM C++ standard library", CUSTOM],
            'static_analyzer': [True, "Install the static analyser of Clang", CUSTOM],
            'skip_all_tests': [False, "Skip running of tests", CUSTOM],
            # The sanitizer tests often fail on HPC systems due to the 'weird' environment.
            'skip_sanitizer_tests': [True, "Do not run the sanitizer tests", CUSTOM],
            'default_cuda_capability': [None, "Default CUDA capability specified for clang, e.g. '7.5'", CUSTOM],
            'build_extra_clang_tools': [False, "Build extra Clang tools", CUSTOM],
        })
        # disable regular out-of-source build, too simplistic for Clang to work
        extra_vars['separate_build_dir'][0] = False
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Clang."""

        super(EB_Clang, self).__init__(*args, **kwargs)
        self.llvm_src_dir = None
        self.llvm_obj_dir_stage1 = None
        self.llvm_obj_dir_stage2 = None
        self.llvm_obj_dir_stage3 = None
        self.make_parallel_opts = ""

    def check_readiness_step(self):
        """Fail early on RHEL 5.x and derivatives because of known bug in libc."""
        super(EB_Clang, self).check_readiness_step()
        # RHEL 5.x have a buggy libc.  Building stage 2 will fail.
        if get_os_name() in ['redhat', 'RHEL', 'centos', 'SL'] and get_os_version().startswith('5.'):
            raise EasyBuildError("Can not build Clang on %s v5.x: libc is buggy, building stage 2 will fail. "
                                 "See http://stackoverflow.com/questions/7276828/", get_os_name())

    def extract_step(self):
        """
        Prepare a combined LLVM source tree.  The layout is:
        llvm/             Unpack llvm-*.tar.gz here
          projects/
            compiler-rt/  Unpack compiler-rt-*.tar.gz here
            openmp/       Unpack openmp-*.tar.xz here
          tools/
            clang/        Unpack clang-*.tar.gz here
              tools/
                extra/    Unpack clang-tools-extra-*.tar.gz here
            polly/        Unpack polly-*.tar.gz here
            libcxx/       Unpack libcxx-*.tar.gz here
            libcxxabi/    Unpack libcxxabi-*.tar.gz here
            lld/          Unpack lld-*.tar.gz here
        libunwind/        Unpack libunwind-*.tar.gz here
        """

        # Extract everything into separate directories.
        super(EB_Clang, self).extract_step()

        # Find the full path to the directory that was unpacked from llvm-*.tar.gz.
        for tmp in self.src:
            if tmp['name'].startswith("llvm-"):
                self.llvm_src_dir = tmp['finalpath']
                break

        if self.llvm_src_dir is None:
            raise EasyBuildError("Could not determine LLVM source root (LLVM source was not unpacked?)")

        src_dirs = {}

        def find_source_dir(globpatterns, targetdir):
            """Search for directory with globpattern and rename it to targetdir"""
            if not isinstance(globpatterns, list):
                globpatterns = [globpatterns]

            glob_src_dirs = [glob_dir for globpattern in globpatterns for glob_dir in glob.glob(globpattern)]
            if len(glob_src_dirs) != 1:
                raise EasyBuildError("Failed to find exactly one source directory for pattern %s: %s", globpatterns,
                                     glob_src_dirs)
            src_dirs[glob_src_dirs[0]] = targetdir

        find_source_dir('compiler-rt-*', os.path.join(self.llvm_src_dir, 'projects', 'compiler-rt'))

        if self.cfg["usepolly"]:
            find_source_dir('polly-*', os.path.join(self.llvm_src_dir, 'tools', 'polly'))

        if self.cfg["build_lld"]:
            find_source_dir('lld-*', os.path.join(self.llvm_src_dir, 'tools', 'lld'))
            if LooseVersion(self.version) >= LooseVersion('12.0.1'):
                find_source_dir('libunwind-*', os.path.normpath(os.path.join(self.llvm_src_dir, '..', 'libunwind')))

        if self.cfg["libcxx"]:
            find_source_dir('libcxx-*', os.path.join(self.llvm_src_dir, 'projects', 'libcxx'))
            find_source_dir('libcxxabi-*', os.path.join(self.llvm_src_dir, 'projects', 'libcxxabi'))

        find_source_dir(['clang-[1-9]*', 'cfe-*'], os.path.join(self.llvm_src_dir, 'tools', 'clang'))

        if self.cfg["build_extra_clang_tools"]:
            find_source_dir('clang-tools-extra-*', os.path.join(self.llvm_src_dir, 'tools', 'clang', 'tools', 'extra'))

        if LooseVersion(self.version) >= LooseVersion('3.8'):
            find_source_dir('openmp-*', os.path.join(self.llvm_src_dir, 'projects', 'openmp'))

        for src in self.src:
            for (dirname, new_path) in src_dirs.items():
                if src['name'].startswith(dirname):
                    old_path = os.path.join(src['finalpath'], dirname)
                    try:
                        shutil.move(old_path, new_path)
                    except IOError as err:
                        raise EasyBuildError("Failed to move %s to %s: %s", old_path, new_path, err)
                    src['finalpath'] = new_path
                    break

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""
        super(EB_Clang, self).prepare_step(*args, **kwargs)

        build_targets = self.cfg['build_targets']
        if build_targets is None:
            arch = get_cpu_architecture()
            try:
                default_targets = DEFAULT_TARGETS_MAP[arch][:]
                # If CUDA is included as a dep, add NVPTX as a target (could also support AMDGPU if we knew how)
                if get_software_root("CUDA"):
                    default_targets += ["NVPTX"]
                self.cfg['build_targets'] = build_targets = default_targets
                self.log.debug("Using %s as default build targets for CPU/GPU architecture %s.", default_targets, arch)
            except KeyError:
                raise EasyBuildError("No default build targets defined for CPU architecture %s.", arch)

        # carry on with empty list from this point forward if no build targets are specified
        if build_targets is None:
            self.cfg['build_targets'] = build_targets = []

        unknown_targets = [target for target in build_targets if target not in CLANG_TARGETS]

        if unknown_targets:
            raise EasyBuildError("Some of the chosen build targets (%s) are not in %s.",
                                 ', '.join(unknown_targets), ', '.join(CLANG_TARGETS))

        if LooseVersion(self.version) < LooseVersion('3.4') and "R600" in build_targets:
            raise EasyBuildError("Build target R600 not supported in < Clang-3.4")

        if LooseVersion(self.version) > LooseVersion('3.3') and "MBlaze" in build_targets:
            raise EasyBuildError("Build target MBlaze is not supported anymore in > Clang-3.3")

    def configure_step(self):
        """Run CMake for stage 1 Clang."""

        if all(dep['name'] != 'ncurses' for dep in self.cfg['dependencies']):
            print_warning('Clang requires ncurses to run, did you forgot to add it to dependencies?')

        self.llvm_obj_dir_stage1 = os.path.join(self.builddir, 'llvm.obj.1')
        if self.cfg['bootstrap']:
            self.llvm_obj_dir_stage2 = os.path.join(self.builddir, 'llvm.obj.2')
            self.llvm_obj_dir_stage3 = os.path.join(self.builddir, 'llvm.obj.3')

        if LooseVersion(self.version) >= LooseVersion('3.3'):
            disable_san_tests = False
            # all sanitizer tests will fail when there's a limit on the vmem
            # this is ugly but I haven't found a cleaner way so far
            (vmemlim, ec) = run_cmd("ulimit -v", regexp=False)
            if not vmemlim.startswith("unlimited"):
                disable_san_tests = True
                self.log.warn("There is a virtual memory limit set of %s KB. The tests of the "
                              "sanitizers will be disabled as they need unlimited virtual "
                              "memory unless --strict=error is used." % vmemlim.strip())

            # the same goes for unlimited stacksize
            (stacklim, ec) = run_cmd("ulimit -s", regexp=False)
            if stacklim.startswith("unlimited"):
                disable_san_tests = True
                self.log.warn("The stacksize limit is set to unlimited. This causes the ThreadSanitizer "
                              "to fail. The sanitizers tests will be disabled unless --strict=error is used.")

            if (disable_san_tests or self.cfg['skip_sanitizer_tests']) and build_option('strict') != run.ERROR:
                self.log.debug("Disabling the sanitizer tests")
                self.disable_sanitizer_tests()

        # Create and enter build directory.
        mkdir(self.llvm_obj_dir_stage1)
        change_dir(self.llvm_obj_dir_stage1)

        # GCC and Clang are installed in different prefixes and Clang will not
        # find the GCC installation on its own.
        # First try with GCCcore, as GCC built on top of GCCcore is just a wrapper for GCCcore and binutils,
        # instead of a full-fledge compiler
        gcc_prefix = get_software_root('GCCcore')

        # If that doesn't work, try with GCC
        if gcc_prefix is None:
            gcc_prefix = get_software_root('GCC')

        # If that doesn't work either, print error and exit
        if gcc_prefix is None:
            raise EasyBuildError("Can't find GCC or GCCcore to use")

        self.cfg.update('configopts', "-DGCC_INSTALL_PREFIX='%s'" % gcc_prefix)
        self.log.debug("Using %s as GCC_INSTALL_PREFIX", gcc_prefix)

        # Configure some default options
        if self.cfg["enable_rtti"]:
            self.cfg.update('configopts', '-DLLVM_REQUIRES_RTTI=ON')
            self.cfg.update('configopts', '-DLLVM_ENABLE_RTTI=ON')
            self.cfg.update('configopts', '-DLLVM_ENABLE_EH=ON')
        if self.cfg["default_openmp_runtime"]:
            self.cfg.update(
                'configopts',
                '-DCLANG_DEFAULT_OPENMP_RUNTIME=%s' % self.cfg["default_openmp_runtime"]
            )

        if self.cfg['assertions']:
            self.cfg.update('configopts', "-DLLVM_ENABLE_ASSERTIONS=ON")
        else:
            self.cfg.update('configopts', "-DLLVM_ENABLE_ASSERTIONS=OFF")

        if self.cfg["usepolly"]:
            self.cfg.update('configopts', "-DLINK_POLLY_INTO_TOOLS=ON")

        # If Z3 is included as a dep, enable support in static analyzer (if enabled)
        if self.cfg["static_analyzer"] and LooseVersion(self.version) >= LooseVersion('9.0.0'):
            z3_root = get_software_root("Z3")
            if z3_root:
                self.cfg.update('configopts', "-DLLVM_ENABLE_Z3_SOLVER=ON")
                self.cfg.update('configopts', "-DLLVM_Z3_INSTALL_DIR=%s" % z3_root)

        build_targets = self.cfg['build_targets']

        if self.cfg["usepolly"] and "NVPTX" in build_targets:
            self.cfg.update('configopts', "-DPOLLY_ENABLE_GPGPU_CODEGEN=ON")

        self.cfg.update('configopts', '-DLLVM_TARGETS_TO_BUILD="%s"' % ';'.join(build_targets))

        if self.cfg['parallel']:
            self.make_parallel_opts = "-j %s" % self.cfg['parallel']

        # If hwloc is included as a dep, use it in OpenMP runtime for affinity
        hwloc_root = get_software_root('hwloc')
        if hwloc_root:
            self.cfg.update('configopts', '-DLIBOMP_USE_HWLOC=ON')
            self.cfg.update('configopts', '-DLIBOMP_HWLOC_INSTALL_DIR=%s' % hwloc_root)

        # If 'NVPTX' is in the build targets we assume the user would like OpenMP offload support as well
        if 'NVPTX' in build_targets:
            # list of CUDA compute capabilities to use can be specifed in two ways (where (2) overrules (1)):
            # (1) in the easyconfig file, via the custom cuda_compute_capabilities;
            # (2) in the EasyBuild configuration, via --cuda-compute-capabilities configuration option;
            ec_cuda_cc = self.cfg['cuda_compute_capabilities']
            cfg_cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cfg_cuda_cc or ec_cuda_cc or []
            if not cuda_cc:
                raise EasyBuildError("Can't build Clang with CUDA support "
                                     "without specifying 'cuda-compute-capabilities'")
            default_cc = self.cfg['default_cuda_capability'] or min(cuda_cc)
            if not self.cfg['default_cuda_capability']:
                print_warning("No default CUDA capability defined! "
                              "Using '%s' taken as minimum from 'cuda_compute_capabilities'" % default_cc)
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            default_cc = default_cc.replace('.', '')
            self.cfg.update('configopts', '-DCLANG_OPENMP_NVPTX_DEFAULT_ARCH=sm_%s' % default_cc)
            self.cfg.update('configopts', '-DLIBOMPTARGET_NVPTX_COMPUTE_CAPABILITIES=%s' % ','.join(cuda_cc))
        # If we don't want to build with CUDA (not in dependencies) trick CMakes FindCUDA module into not finding it by
        # using the environment variable which is used as-is and later checked for a falsy value when determining
        # whether CUDA was found
        if not get_software_root('CUDA'):
            setvar('CUDA_NVCC_EXECUTABLE', 'IGNORE')

        self.log.info("Configuring")
        super(EB_Clang, self).configure_step(srcdir=self.llvm_src_dir)

    def disable_sanitizer_tests(self):
        """Disable the tests of all the sanitizers by removing the test directories from the build system"""
        if LooseVersion(self.version) < LooseVersion('3.6'):
            # for Clang 3.5 and lower, the tests are scattered over several CMakeLists.
            # We loop over them, and patch out the rule that adds the sanitizers tests to the testsuite
            patchfiles = ['lib/asan', 'lib/dfsan', 'lib/lsan', 'lib/msan', 'lib/tsan', 'lib/ubsan']

            for patchfile in patchfiles:
                cmakelists = os.path.join(self.llvm_src_dir, 'projects/compiler-rt', patchfile, 'CMakeLists.txt')
                if os.path.exists(cmakelists):
                    regex_subs = [(r'.*add_subdirectory\(lit_tests\).*', '')]
                    apply_regex_substitutions(cmakelists, regex_subs)

            # There is a common part seperate for the specific saniters, we disable all the common tests
            cmakelists = os.path.join('projects', 'compiler-rt', 'lib', 'sanitizer_common', 'CMakeLists.txt')
            regex_subs = [(r'.*add_subdirectory\(tests\).*', '')]
            apply_regex_substitutions(cmakelists, regex_subs)

        else:
            # In Clang 3.6, the sanitizer tests are grouped together in one CMakeLists
            # We patch out adding the subdirectories with the sanitizer tests
            cmakelists_tests = os.path.join(self.llvm_src_dir, 'projects', 'compiler-rt', 'test', 'CMakeLists.txt')
            regex_subs = []
            if LooseVersion(self.version) >= LooseVersion('5.0'):
                regex_subs.append((r'compiler_rt_test_runtime.*san.*', ''))
            else:
                regex_subs.append((r'add_subdirectory\((.*san|sanitizer_common)\)', ''))

            apply_regex_substitutions(cmakelists_tests, regex_subs)

    def build_with_prev_stage(self, prev_obj, next_obj):
        """Build Clang stage N using Clang stage N-1"""

        # Create and enter build directory.
        mkdir(next_obj)
        change_dir(next_obj)

        # Configure.
        CC = os.path.join(prev_obj, 'bin', 'clang')
        CXX = os.path.join(prev_obj, 'bin', 'clang++')

        options = "-DCMAKE_INSTALL_PREFIX=%s " % self.installdir
        options += "-DCMAKE_C_COMPILER='%s' " % CC
        options += "-DCMAKE_CXX_COMPILER='%s' " % CXX
        options += self.cfg['configopts']
        options += "-DCMAKE_BUILD_TYPE=%s" % self.build_type

        self.log.info("Configuring")
        run_cmd("cmake %s %s" % (options, self.llvm_src_dir), log_all=True)

        self.log.info("Building")
        run_cmd("make %s" % self.make_parallel_opts, log_all=True)

    def run_clang_tests(self, obj_dir):
        """Run Clang tests in specified directory (unless disabled)."""
        if not self.cfg['skip_all_tests']:
            change_dir(obj_dir)

            self.log.info("Running tests")
            run_cmd("make %s check-all" % self.make_parallel_opts, log_all=True)

    def build_step(self):
        """Build Clang stage 1, 2, 3"""

        # Stage 1: build using system compiler.
        self.log.info("Building stage 1")
        change_dir(self.llvm_obj_dir_stage1)
        super(EB_Clang, self).build_step()

        if self.cfg['bootstrap']:
            # Stage 1: run tests.
            self.run_clang_tests(self.llvm_obj_dir_stage1)

            self.log.info("Building stage 2")
            self.build_with_prev_stage(self.llvm_obj_dir_stage1, self.llvm_obj_dir_stage2)
            self.run_clang_tests(self.llvm_obj_dir_stage2)

            self.log.info("Building stage 3")
            self.build_with_prev_stage(self.llvm_obj_dir_stage2, self.llvm_obj_dir_stage3)
            # Don't run stage 3 tests here, do it in the test step.

    def test_step(self):
        """Run Clang tests."""
        if self.cfg['bootstrap']:
            self.run_clang_tests(self.llvm_obj_dir_stage3)
        else:
            self.run_clang_tests(self.llvm_obj_dir_stage1)

    def install_step(self):
        """Install stage 3 binaries."""

        if self.cfg['bootstrap']:
            change_dir(self.llvm_obj_dir_stage3)
        else:
            change_dir(self.llvm_obj_dir_stage1)
        super(EB_Clang, self).install_step()

        # the static analyzer is not installed by default
        # we do it by hand
        if self.cfg['static_analyzer'] and LooseVersion(self.version) < LooseVersion('3.8'):
            try:
                tools_src_dir = os.path.join(self.llvm_src_dir, 'tools', 'clang', 'tools')
                analyzer_target_dir = os.path.join(self.installdir, 'libexec', 'clang-analyzer')
                bindir = os.path.join(self.installdir, 'bin')
                for scan_dir in ['scan-build', 'scan-view']:
                    shutil.copytree(os.path.join(tools_src_dir, scan_dir), os.path.join(analyzer_target_dir, scan_dir))
                    os.symlink(os.path.relpath(bindir, os.path.join(analyzer_target_dir, scan_dir)),
                               os.path.join(analyzer_target_dir, scan_dir, 'bin'))
                    os.symlink(os.path.relpath(os.path.join(analyzer_target_dir, scan_dir, scan_dir), bindir),
                               os.path.join(bindir, scan_dir))

                mandir = os.path.join(self.installdir, 'share', 'man', 'man1')
                os.makedirs(mandir)
                shutil.copy2(os.path.join(tools_src_dir, 'scan-build', 'scan-build.1'), mandir)
            except OSError as err:
                raise EasyBuildError("Failed to copy static analyzer dirs to install dir: %s", err)

    def sanity_check_step(self):
        """Custom sanity check for Clang."""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': [
                "bin/clang", "bin/clang++", "bin/llvm-ar", "bin/llvm-nm", "bin/llvm-as", "bin/opt", "bin/llvm-link",
                "bin/llvm-config", "bin/llvm-symbolizer", "include/llvm-c/Core.h", "include/clang-c/Index.h",
                "lib/libclang.%s" % shlib_ext, "lib/clang/%s/include/stddef.h" % self.version,
            ],
            'dirs': ["include/clang", "include/llvm", "lib/clang/%s/lib" % self.version],
        }
        if self.cfg['static_analyzer']:
            custom_paths['files'].extend(["bin/scan-build", "bin/scan-view"])

        if self.cfg['build_extra_clang_tools'] and LooseVersion(self.version) >= LooseVersion('3.4'):
            custom_paths['files'].extend(["bin/clang-tidy"])

        if self.cfg["usepolly"]:
            custom_paths['files'].extend(["lib/LLVMPolly.%s" % shlib_ext])
            custom_paths['dirs'].extend(["include/polly"])

        if self.cfg["build_lld"]:
            custom_paths['files'].extend(["bin/lld"])

        if self.cfg["libcxx"]:
            custom_paths['files'].extend(["lib/libc++.%s" % shlib_ext])
            custom_paths['files'].extend(["lib/libc++abi.%s" % shlib_ext])

        if LooseVersion(self.version) >= LooseVersion('3.8'):
            custom_paths['files'].extend(["lib/libomp.%s" % shlib_ext, "lib/clang/%s/include/omp.h" % self.version])

        if 'NVPTX' in self.cfg['build_targets']:
            arch = get_cpu_architecture()
            # Check architecture explicitly since Clang uses potentially
            # different names
            if arch == X86_64:
                arch = 'x86_64'
            elif arch == POWER:
                arch = 'ppc64'
            elif arch == AARCH64:
                arch = 'aarch64'
            else:
                print_warning("Unknown CPU architecture (%s) for OpenMP offloading!" % arch)
            custom_paths['files'].extend(["lib/libomptarget.%s" % shlib_ext,
                                          "lib/libomptarget-nvptx.a",
                                          "lib/libomptarget.rtl.cuda.%s" % shlib_ext,
                                          "lib/libomptarget.rtl.%s.%s" % (arch, shlib_ext)])

        custom_commands = ['clang --help', 'clang++ --help', 'llvm-config --cxxflags']
        super(EB_Clang, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Custom variables for Clang module."""
        txt = super(EB_Clang, self).make_module_extra()
        # we set the symbolizer path so that asan/tsan give meanfull output by default
        asan_symbolizer_path = os.path.join(self.installdir, 'bin', 'llvm-symbolizer')
        txt += self.module_generator.set_environment('ASAN_SYMBOLIZER_PATH', asan_symbolizer_path)
        return txt
