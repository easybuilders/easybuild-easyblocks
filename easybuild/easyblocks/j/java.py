##
# Copyright 2012-2026 Ghent University
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
EasyBlock for installing Java, implemented as an easyblock

@author: Jens Timmerman (Ghent University)
@author: Kenneth Hoste (Ghent University)
"""
import glob
import os
import stat

from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, change_dir, clean_dir, copy_dir, copy_file, which
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, POWER, RISCV64, X86_64, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.utilities import nub


def find_sysroot_interpreter_and_paths(logger=None):
    """
    Find sysroot library paths and isolate the ELF interpreter.

    :param sysroot: Path to the target sysroot.
    :param logger: Logger for diagnostic messages.
    :return: Tuple of (ELF interpreter path, sysroot library paths).
    """
    sysroot = build_option('sysroot')
    if not sysroot:
        raise EasyBuildError("No 'sysroot' build option specified")

    sysroot_lib_paths = glob.glob(os.path.join(sysroot, 'lib*'))
    sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*'))
    sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*', 'gcc', '*', '*'))

    if sysroot_lib_paths:
        if logger:
            logger.info("List of library paths in %s to add to RPATH section: %s", sysroot, sysroot_lib_paths)
    else:
        raise EasyBuildError("sysroot has no library paths, that can't be right!")

    elf_interp = None

    for ld_glob_pattern in (r'ld-linux-*.so.*', r'ld*.so.*'):
        matches = glob.glob(os.path.join(sysroot, 'lib*', ld_glob_pattern))
        if logger:
            logger.debug("Paths for ELF interpreter via '%s' pattern: %s", ld_glob_pattern, matches)

        if not matches:
            continue

        # Keep the symbolic link path, but ensure all matches resolve
        # to the same underlying interpreter.
        real_paths = nub([os.path.realpath(path) for path in matches])

        if len(real_paths) != 1:
            raise EasyBuildError("Multiple different unique ELF interpreters found: %s", real_paths)

        elf_interp = matches[0]
        if logger:
            logger.info("ELF interpreter found at %s", elf_interp)
        break

    if elf_interp is None:
        raise EasyBuildError("Failed to isolate ELF interpreter!")

    return elf_interp, sysroot_lib_paths


def patch_path_for_sysroot(path, rpath_updates=[], interpreter=None, logger=None, shrink_rpath=True):
    """
    Patch the ELF interpreter and/or RPATH of a dynamically linked file.
    """
    res = run_shell_cmd("file '%s'" % path, hidden=True)
    file_info = res.output

    if "dynamically linked" not in file_info:
        if logger:
            logger.debug("File is not dynamically linked, ignoring %s", path)
        return
    is_executable = "executable" in file_info

    if not which('patchelf'):
        raise EasyBuildError("patchelf not found via $PATH, required to patch RPATH section in binaries/libraries")

    if rpath_updates:
        res = run_shell_cmd("patchelf --print-rpath '%s'" % path, hidden=True)
        curr_rpath = res.output.strip()
        if logger:
            logger.debug("RPATH for %s before patchelf: %s", path, curr_rpath)

        rpath_entries = curr_rpath.split(':') if curr_rpath else []
        new_entries = rpath_entries + [
            lib_path for lib_path in rpath_updates
            if lib_path not in rpath_entries
        ]
        new_rpath = ':'.join(new_entries)

        run_shell_cmd("patchelf --set-rpath '%s' '%s'" % (new_rpath, path), hidden=True)

        if shrink_rpath:
            run_shell_cmd("patchelf --shrink-rpath '%s'" % path, hidden=True)

    # According to https://github.com/NixOS/patchelf/issues/524 the order we do things matters
    # so we must change the interpreter only _after_ changing the RPATHs
    if interpreter is not None and is_executable:
        res = run_shell_cmd("patchelf --print-interpreter '%s'" % path, hidden=True)
        orig_interp = res.output.strip()
        if logger:
            logger.debug("ELF interpreter for %s before updating: %s", path, orig_interp)

        run_shell_cmd("patchelf --set-interpreter '%s' '%s'" % (interpreter, path), hidden=True)

        res = run_shell_cmd("patchelf --print-interpreter '%s'" % path, hidden=True)
        curr_interp = res.output.strip()
        if curr_interp != interpreter:
            raise EasyBuildError(
                "Failed to set ELF interpreter for %s: expected %s, got %s", path, interpreter, curr_interp
            )

    if rpath_updates:
        res = run_shell_cmd("patchelf --print-rpath '%s'" % path, hidden=True)
        curr_rpath = res.output.strip()
        if logger:
            logger.debug(
                "RPATH for %s after updating%s: %s", path, " and shrinking" if shrink_rpath else "", curr_rpath,
            )


class EB_Java(PackedBinary):
    """Support for installing Java as a packed binary file (.tar.gz)
    Use the PackedBinary easyblock and set some extra paths.
    """

    def __init__(self, *args, **kwargs):
        """ Init the Java easyblock adding a new jdkarch template var """
        myarch = get_cpu_architecture()
        if myarch == AARCH64:
            jdkarch = 'aarch64'
        elif myarch == POWER:
            jdkarch = 'ppc64le'
        elif myarch == RISCV64:
            jdkarch = 'riscv64'
        elif myarch == X86_64:
            jdkarch = 'x64'
        else:
            raise EasyBuildError("Architecture %s is not supported for Java on EasyBuild", myarch)

        super().__init__(*args, **kwargs)

        self.cfg.template_values['jdkarch'] = jdkarch
        self.cfg.generate_template_values()

    def extract_step(self):
        """Unpack the source"""
        if LooseVersion(self.version) < LooseVersion('1.7'):

            copy_file(self.src[0]['path'], self.builddir)
            adjust_permissions(os.path.join(self.builddir, self.src[0]['name']), stat.S_IXUSR, add=True)

            change_dir(self.builddir)
            run_shell_cmd(os.path.join(self.builddir, self.src[0]['name']), stdin='')
        else:
            PackedBinary.extract_step(self)
            adjust_permissions(self.builddir, stat.S_IWUSR, add=True, recursive=True)

    def install_step(self):
        """Custom install step: just copy unpacked installation files."""
        if LooseVersion(self.version) < LooseVersion('1.7'):
            clean_dir(self.installdir)
            copy_dir(os.path.join(self.builddir, 'jdk%s' % self.version), self.installdir, dirs_exist_ok=True)
        else:
            PackedBinary.install_step(self)

    def post_processing_step(self):
        """
        Custom post-installation step:
        - ensure correct glibc is used when installing into custom sysroot and using RPATH
        """
        super().post_processing_step()

        # patch binaries and libraries when using alternate sysroot in combination with RPATH
        sysroot = build_option('sysroot')
        if sysroot and self.toolchain.use_rpath:
            try:
                # list of paths in sysroot to consider for adding to RPATH section
                elf_interp, sysroot_lib_paths = find_sysroot_interpreter_and_paths(self.log)

                # Expand paths in PATH and make sure these are unique real paths
                bindirs = self.module_load_environment.PATH.expand_paths(self.installdir)
                bindirs = [os.path.realpath(os.path.join(self.installdir, bindir)) for bindir in bindirs]
                for bindir in bindirs:
                    for path in os.listdir(bindir):
                        path = os.path.join(bindir, path)
                        patch_path_for_sysroot(
                            path, rpath_updates=sysroot_lib_paths, interpreter=elf_interp, logger=self.log
                        )

                # Expand paths in LIBRARY_PATH and make sure these are unique real paths
                libdirs = self.module_load_environment.LIBRARY_PATH.expand_paths(self.installdir)
                libdirs = [os.path.realpath(os.path.join(self.installdir, ld)) for ld in libdirs]
                shlib_ext = '.' + get_shared_lib_ext()
                for libdir in libdirs:
                    for path, _, filenames in os.walk(libdir):
                        shlibs = [os.path.join(path, x) for x in filenames if x.endswith(shlib_ext)]
                        for shlib in shlibs:
                            patch_path_for_sysroot(
                                shlib, rpath_updates=sysroot_lib_paths, interpreter=elf_interp, logger=self.log
                            )

            except OSError as err:
                raise EasyBuildError("Failed to patch RPATH section in binaries/libraries: %s", err)

    def sanity_check_step(self):
        """Custom sanity check for Java."""
        custom_paths = {
            'files': ['bin/java', 'bin/javac'],
            'dirs': ['lib'],
        }

        custom_commands = [
            "java -help",
            "javac -help",
        ]

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """
        Set extra environment variables on module load
        """
        txt = super().make_module_extra()
        # set $JAVA_HOME to installation directory
        txt += self.module_generator.set_environment('JAVA_HOME', self.installdir)
        # disable signal catching in UCX, as it conflicts with JVM triggering segfaults
        # see https://github.com/openucx/ucx/issues/4870
        txt += self.module_generator.set_environment('UCX_ERROR_SIGNALS', '')

        return txt
