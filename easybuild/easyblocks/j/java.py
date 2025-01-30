##
# Copyright 2012-2024 Ghent University
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

from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_dir, copy_file, remove_dir, which
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import AARCH64, POWER, RISCV64, X86_64, get_cpu_architecture, get_shared_lib_ext
from easybuild.tools.utilities import nub


class EB_Java(PackedBinary):
    """Support for installing Java as a packed binary file (.tar.gz)
    Use the PackedBinary easyblock and set some extra paths.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Java easyblock."""
        extra_vars = PackedBinary.extra_options(extra_vars)
        extra_vars.update({
            # Overwrite the default value for run_rpath_sanity_check to True, since we have RPATH patching with
            # patchelf for Java
            'run_rpath_sanity_check': [True, "Whether or not to run the RPATH sanity check", CUSTOM],
            'patch_rpaths': [True, "Whether or not to use patchelf to add relevant dirs (from LIBRARY_PATH or, "
                                    "if sysroot is enabled, from default libdirs in the sysroot) to RPATH", CUSTOM],
            'extra_rpaths': [['%(installdir)s/lib/server'], "List of directories to add to the RPATH, aside from the "
                                   "default ones added by patch_rpaths. Any $EBROOT* environment variables will be "
                                   "replaced by their respective values before setting the RPATH.", CUSTOM],
            'patch_interpreter': [True, "Whether or not to use patchelf to patch the interpreter in executables when "
                                         "sysroot is used", CUSTOM],
            # Also patch shared libraries in lib/server by default
            'bin_lib_subdirs': [['bin', 'lib', 'lib/server', 'lib64', 'lib64/server'],
                                "List of subdirectories for binaries and libraries, which is used "
                                "during sanity check to check RPATH linking and banned/required libraries", CUSTOM],
        })
        return extra_vars

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
            run_cmd(os.path.join(self.builddir, self.src[0]['name']), log_all=True, simple=True, inp='')
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

#     def post_install_step(self):
#         """
#         Custom post-installation step:
#         - ensure relevant paths from LIBRARY_PATH are added to RPATH if using RPATH support
#         - ensure correct glibc is used when installing into custom sysroot and using RPATH
#         """
#         super(EB_Java, self).post_install_step()
# 
#         # Get sysroot for later
#         sysroot = build_option('sysroot')
# 
#         extra_rpaths = []
#         # get relevant LIBRARY_PATH entries to add to RPATH if RPATH support is enabled:
#         if self.toolchain.use_rpath:
#             # Fail early if patchelf isn't found - we need it
#             if not which('patchelf'):
#                 error_msg = "patchelf not found via $PATH, required to patch RPATH section in binaries/libraries"
#                 raise EasyBuildError(error_msg)
#             # Some libraries, e.g. libjvm.so, are located in $EBROOTJAVA/lib/server, so let's add $ORIGIN/../lib/server
#             extra_rpaths += ['$ORIGIN/../lib/server']
#             # Get LIBRARY_PATH as a list and add it to the extra paths to be added to RPATH
#             library_path = os.environ.get('LIBRARY_PATH', '').split(':')
#             if library_path:
#                 self.log.info("List of library paths from LIBRARY_PATH to be added to RPATH section: %s", library_path)
#                 extra_rpaths += library_path
# 
#         # If using sysroot AND rpath, add list of library paths in sysroot to consider for adding to RPATH section
#         if sysroot and self.toolchain.use_rpath:
#             sysroot_lib_paths = glob.glob(os.path.join(sysroot, 'lib*'))
#             sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*'))
#             sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*', 'gcc', '*', '*'))
#             if sysroot_lib_paths:
#                 self.log.info("List of library paths in %s to add to RPATH section: %s", sysroot, sysroot_lib_paths)
#                 extra_rpaths += sysroot_lib_paths
# 
#         # If using sysroot, locate ELF interpreter
#         elf_interp = None
#         if sysroot:
#             # find path to ELF interpreter
#             for ld_glob_pattern in (r'ld-linux-*.so.*', r'ld*.so.*'):
#                 res = glob.glob(os.path.join(sysroot, 'lib*', ld_glob_pattern))
#                 self.log.debug("Paths for ELF interpreter via '%s' pattern: %s", ld_glob_pattern, res)
#                 if res:
#                     # if there are multiple hits, make sure they resolve to the same paths,
#                     # but keep using the symbolic link, not the resolved path!
#                     real_paths = nub([os.path.realpath(x) for x in res])
#                     if len(real_paths) == 1:
#                         elf_interp = res[0]
#                         self.log.info("ELF interpreter found at %s", elf_interp)
#                         break
#                     else:
#                         raise EasyBuildError("Multiple different unique ELF interpreters found: %s", real_paths)
# 
#             if elf_interp is None:
#                 raise EasyBuildError("Failed to isolate ELF interpreter!")
# 
#         # Now that we have collected additional RPATHS and elf interpeter, set/add them (when relevant)
#         if extra_rpaths or elf_interp is not None:
#             try:
#                 module_guesses = self.make_module_req_guess()
# 
#                 # Set ELF interpreter and/or add to RPATH of binaries
#                 bindirs = [os.path.join(self.installdir, bindir) for bindir in module_guesses['PATH'] if
#                            os.path.exists(os.path.join(self.installdir, bindir))]
#                 # Make sure these are unique real paths
#                 bindirs = list(set([os.path.realpath(path) for path in bindirs]))
#                 for bindir in bindirs:
#                     for path in os.listdir(bindir):
#                         path = os.path.join(bindir, path)
#                         out, _ = run_cmd("file %s" % path, trace=False)
#                         if "dynamically linked" in out:
#                             # Set ELF interpreter if needed
#                             if elf_interp is not None:
#                                 out, _ = run_cmd("patchelf --print-interpreter %s" % path, trace=False)
#                                 self.log.debug("ELF interpreter for %s: %s" % (path, out))
# 
#                                 run_cmd("patchelf --set-interpreter %s %s" % (elf_interp, path), trace=False)
# 
#                                 out, _ = run_cmd("patchelf --print-interpreter %s" % path, trace=False)
#                                 self.log.debug("ELF interpreter for %s: %s" % (path, out))
# 
#                             # Add to RPATH if needed
#                             if extra_rpaths:
#                                 out, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
#                                 curr_rpath = out.strip()
#                                 self.log.debug("RPATH for %s: %s" % (path, curr_rpath))
# 
#                                 new_rpath = ':'.join([curr_rpath] + extra_rpaths)
#                                 # note: it's important to wrap the new RPATH value in single quotes,
#                                 # to avoid magic values like $ORIGIN being resolved by the shell
#                                 run_cmd("patchelf --force-rpath --set-rpath '%s' %s" % (new_rpath, path), trace=False)
# 
#                                 curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
#                                 self.log.debug("RPATH for %s (prior to shrinking): %s" % (path, curr_rpath))
# 
#                                 run_cmd("patchelf --force-rpath --shrink-rpath %s" % path, trace=False)
# 
#                                 curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
#                                 self.log.debug("RPATH for %s (after shrinking): %s" % (path, curr_rpath))
# 
#             except OSError as err:
#                 raise EasyBuildError("Failed to patch RPATH or ELF interpreter section in binaries: %s", err)
# 
#         # Add to RPATH of libraries
#         if extra_rpaths:
#             try:
#                 libdirs = [os.path.join(self.installdir, libdir) for libdir in module_guesses['LIBRARY_PATH'] if
#                            os.path.exists(os.path.join(self.installdir, libdir))]
#                 # Make sure these are unique real paths
#                 libdirs = list(set([os.path.realpath(path) for path in libdirs]))
#                 shlib_ext = '.' + get_shared_lib_ext()
#                 for libdir in libdirs:
#                     for path, _, filenames in os.walk(libdir):
#                         shlibs = [os.path.join(path, x) for x in filenames if x.endswith(shlib_ext)]
#                         # For some reason, Java has some dynamically linked executables in the libdir
#                         # (jexec and jspawnhelper)
#                         # We'll find those and any other dynamically linked exes in the libdir to make sure their
#                         # RPATH is also patched
#                         for filename in filenames:
#                             out, _ = run_cmd("file %s" % os.path.join(path, filename), trace=False)
#                             if "dynamically linked" in out:
#                                 # this is a dynamically linked exe in the libdir, so patch RPATH here too
#                                 shlibs.append(filename)
#                         for shlib in shlibs:
#                             out, _ = run_cmd("patchelf --print-rpath %s" % shlib, simple=False, trace=False)
#                             curr_rpath = out.strip()
#                             self.log.debug("RPATH for %s: %s" % (shlib, curr_rpath))
# 
#                             new_rpath = ':'.join([curr_rpath] + extra_rpaths)
#                             # note: it's important to wrap the new RPATH value in single quotes,
#                             # to avoid magic values like $ORIGIN being resolved by the shell
#                             run_cmd("patchelf --force-rpath --set-rpath '%s' %s" % (new_rpath, shlib), trace=False)
# 
#                             curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % shlib, simple=False, trace=False)
#                             self.log.debug("RPATH for %s (prior to shrinking): %s" % (path, curr_rpath))
# 
#                             run_cmd("patchelf --force-rpath --shrink-rpath %s" % shlib, trace=False)
# 
#                             curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % shlib, simple=False, trace=False)
#                             self.log.debug("RPATH for %s (after shrinking): %s" % (path, curr_rpath))
# 
#             except OSError as err:
#                 raise EasyBuildError("Failed to patch RPATH section in libraries: %s", err)

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
