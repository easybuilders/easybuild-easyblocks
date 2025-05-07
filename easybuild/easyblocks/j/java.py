##
# Copyright 2012-2025 Ghent University
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
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_dir, copy_file, remove_dir, which
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, POWER, RISCV64, X86_64, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.utilities import nub


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

        super(EB_Java, self).__init__(*args, **kwargs)

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
            remove_dir(self.installdir)
            copy_dir(os.path.join(self.builddir, 'jdk%s' % self.version), self.installdir)
        else:
            PackedBinary.install_step(self)

    def post_processing_step(self):
        """
        Custom post-installation step:
        - ensure correct glibc is used when installing into custom sysroot and using RPATH
        """
        super(EB_Java, self).post_processing_step()

        # patch binaries and libraries when using alternate sysroot in combination with RPATH
        sysroot = build_option('sysroot')
        if sysroot and self.toolchain.use_rpath:
            if not which('patchelf'):
                error_msg = "patchelf not found via $PATH, required to patch RPATH section in binaries/libraries"
                raise EasyBuildError(error_msg)

            try:
                # list of paths in sysroot to consider for adding to RPATH section
                sysroot_lib_paths = glob.glob(os.path.join(sysroot, 'lib*'))
                sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*'))
                sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*', 'gcc', '*', '*'))
                if sysroot_lib_paths:
                    self.log.info("List of library paths in %s to add to RPATH section: %s", sysroot, sysroot_lib_paths)

                # find path to ELF interpreter
                elf_interp = None

                for ld_glob_pattern in (r'ld-linux-*.so.*', r'ld*.so.*'):
                    res = glob.glob(os.path.join(sysroot, 'lib*', ld_glob_pattern))
                    self.log.debug("Paths for ELF interpreter via '%s' pattern: %s", ld_glob_pattern, res)
                    if res:
                        # if there are multiple hits, make sure they resolve to the same paths,
                        # but keep using the symbolic link, not the resolved path!
                        real_paths = nub([os.path.realpath(x) for x in res])
                        if len(real_paths) == 1:
                            elf_interp = res[0]
                            self.log.info("ELF interpreter found at %s", elf_interp)
                            break
                        else:
                            raise EasyBuildError("Multiple different unique ELF interpreters found: %s", real_paths)

                if elf_interp is None:
                    raise EasyBuildError("Failed to isolate ELF interpreter!")

                # Expand paths in PATH and make sure these are unique real paths
                bindirs = nub([x for bindir in self.module_load_environment.PATH
                               for x in self.expand_module_search_path(bindir)])
                bindirs = [os.path.realpath(os.path.join(self.installdir, bindir)) for bindir in bindirs]
                for bindir in bindirs:
                    for path in os.listdir(bindir):
                        path = os.path.join(bindir, path)
                        res = run_shell_cmd("file %s" % path, hidden=True)
                        if "dynamically linked" in res.output:

                            res = run_shell_cmd("patchelf --print-interpreter %s" % path)
                            self.log.debug("ELF interpreter for %s: %s" % (path, res.output))

                            run_shell_cmd("patchelf --set-interpreter %s %s" % (elf_interp, path), hidden=True)

                            res = run_shell_cmd("patchelf --print-interpreter %s" % path, hidden=True)
                            self.log.debug("ELF interpreter for %s: %s" % (path, res.output))

                            res = run_shell_cmd("patchelf --print-rpath %s" % path, hidden=True)
                            curr_rpath = res.output.strip()
                            self.log.debug("RPATH for %s: %s" % (path, curr_rpath))

                            new_rpath = ':'.join([curr_rpath] + sysroot_lib_paths)
                            # note: it's important to wrap the new RPATH value in single quotes,
                            # to avoid magic values like $ORIGIN being resolved by the shell
                            run_shell_cmd("patchelf --set-rpath '%s' %s" % (new_rpath, path), hidden=True)

                            res = run_shell_cmd("patchelf --print-rpath %s" % path, hidden=True)
                            self.log.debug("RPATH for %s (prior to shrinking): %s" % (path, res.output))

                            run_shell_cmd("patchelf --shrink-rpath %s" % path, hidden=True)

                            res = run_shell_cmd("patchelf --print-rpath %s" % path, hidden=True)
                            self.log.debug("RPATH for %s (after shrinking): %s" % (path, res.output))

                # Expand paths in LIBRARY_PATH and make sure these are unique real paths
                libdirs = nub([x for ld in self.module_load_environment.LIBRARY_PATH
                               for x in self.expand_module_search_path(ld)])
                libdirs = [os.path.realpath(os.path.join(self.installdir, ld)) for ld in libdirs]
                shlib_ext = '.' + get_shared_lib_ext()
                for libdir in libdirs:
                    for path, _, filenames in os.walk(libdir):
                        shlibs = [os.path.join(path, x) for x in filenames if x.endswith(shlib_ext)]
                        for shlib in shlibs:
                            res = run_shell_cmd("patchelf --print-rpath %s" % shlib, hidden=True)
                            curr_rpath = res.output.strip()
                            self.log.debug("RPATH for %s: %s" % (shlib, curr_rpath))

                            new_rpath = ':'.join([curr_rpath] + sysroot_lib_paths)
                            # note: it's important to wrap the new RPATH value in single quotes,
                            # to avoid magic values like $ORIGIN being resolved by the shell
                            run_shell_cmd("patchelf --set-rpath '%s' %s" % (new_rpath, shlib), hidden=True)

                            res = run_shell_cmd("patchelf --print-rpath %s" % shlib, hidden=True)
                            self.log.debug("RPATH for %s (prior to shrinking): %s" % (path, res.output))

                            run_shell_cmd("patchelf --shrink-rpath %s" % shlib, hidden=True)

                            res = run_shell_cmd("patchelf --print-rpath %s" % shlib, hidden=True)
                            self.log.debug("RPATH for %s (after shrinking): %s" % (path, res.output))

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

        super(EB_Java, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """
        Set $JAVA_HOME to installation directory
        """
        txt = PackedBinary.make_module_extra(self)
        txt += self.module_generator.set_environment('JAVA_HOME', self.installdir)
        return txt
