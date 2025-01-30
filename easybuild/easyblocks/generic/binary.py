##
# Copyright 2009-2024 Ghent University
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
General EasyBuild support for software with a binary installer

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""

import shutil
import os
import stat

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file, mkdir, remove_dir
from easybuild.tools.run import run_cmd

PREPEND_TO_PATH_DEFAULT = ['']


class Binary(EasyBlock):
    """
    Support for installing software that comes in binary form.
    Just copy the sources to the install dir, or use the specified install command.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Binary easyblock."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'extract_sources': [False, "Whether or not to extract sources", CUSTOM],
            'install_cmd': [None, "Install command to be used.", CUSTOM],
            'install_cmds': [None, "List of install commands to be used.", CUSTOM],
            # staged installation can help with the hard (potentially faulty) check on available disk space
            'staged_install': [False, "Perform staged installation via subdirectory of build directory", CUSTOM],
            'prepend_to_path': [PREPEND_TO_PATH_DEFAULT, "Prepend the given directories (relative to install-dir) to "
                                                         "the environment variable PATH in the module file. Default "
                                                         "is the install-dir itself.", CUSTOM],
            # We should start moving away from skipping the RPATH sanity check and towards patching RPATHS
            # using patchelf, see e.g. https://github.com/easybuilders/easybuild-easyblocks/pull/3571
            # The option run_rpath_sanity_check supports a gradual transition where binary installs that properly
            # patch the RPATH can start running the sanity check
            'run_rpath_sanity_check': [False, "Whether or not to run the RPATH sanity check", CUSTOM],
            # Default for patch_rpath should always remain False, because not all licenses allow modification
            # of binaries - even the headers
            'patch_rpaths': [False, "Whether or not to use patchelf to add relevant dirs (from LIBRARY_PATH or, "
                                    "if sysroot is enabled, from default libdirs in the sysroot) to RPATH", CUSTOM],
            'extra_rpaths': [None, "List of directories to add to the RPATH, aside from the default ones added by "
                                   "patch_rpaths. Any $EBROOT* environment variables will be replaced by their "
                                   "respective values before setting the RPATH.", CUSTOM],
            # Default for patch_interpreter should always remain False, because not all licenses allow modification
            # of binaries - even the headers
            'patch_interpreter': [False, "Whether or not to use patchelf to patch the interpreter in executables when "
                                         "sysroot is used", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize Binary-specific variables."""
        super(Binary, self).__init__(*args, **kwargs)

        self.actual_installdir = None
        if self.cfg.get('staged_install', False):
            self.actual_installdir = self.installdir
            self.installdir = os.path.join(self.builddir, 'staged')
            mkdir(self.installdir, parents=True)
            self.log.info("Performing staged installation via %s" % self.installdir)

    def extract_step(self):
        """Copy all source files to the build directory"""

        if self.cfg.get('extract_sources', False):
            super(Binary, self).extract_step()
        else:
            # required for correctly guessing start directory
            self.src[0]['finalpath'] = self.builddir

            # copy source to build dir
            for source in self.src:
                dst = os.path.join(self.builddir, source['name'])
                copy_file(source['path'], dst)
                adjust_permissions(dst, stat.S_IRWXU, add=True)

    def configure_step(self):
        """No configuration, this is binary software"""
        pass

    def build_step(self):
        """No compilation, this is binary software"""
        pass

    def install_step(self):
        """Copy all files in build directory to the install directory"""
        install_cmd = self.cfg.get('install_cmd', None)
        install_cmds = self.cfg.get('install_cmds', [])

        if install_cmd is None and install_cmds is None:
            try:
                # shutil.copytree doesn't allow the target directory to exist already
                remove_dir(self.installdir)
                shutil.copytree(self.cfg['start_dir'], self.installdir, symlinks=self.cfg['keepsymlinks'])
            except OSError as err:
                raise EasyBuildError("Failed to copy %s to %s: %s", self.cfg['start_dir'], self.installdir, err)
        else:
            if install_cmd:
                if not install_cmds:
                    install_cmds = [install_cmd]
                    install_cmd = None
                else:
                    raise EasyBuildError("Don't use both install_cmds and install_cmd, pick one!")

            if isinstance(install_cmds, (list, tuple)):
                for install_cmd in install_cmds:
                    cmd = ' '.join([self.cfg['preinstallopts'], install_cmd, self.cfg['installopts']])
                    self.log.info("Running install command for %s: '%s'..." % (self.name, cmd))
                    run_cmd(cmd, log_all=True, simple=True)
            else:
                raise EasyBuildError("Incorrect value type for install_cmds, should be list or tuple: ",
                                     install_cmds)

    def _get_elf_interpreter_from_sysroot(self):
        """
        Find a path to the ELF interpreter based on the sysroot.
        This function produces an error if either mulitple or no ELF interpreters are found.
        Otherwise, it will return the realpath to the ELF interpreter in the sysroot.
        """
        elf_interp = None
        sysroot = build_option('sysroot')
        # find path to ELF interpreter
        for ld_glob_pattern in (r'ld-linux-*.so.*', r'ld*.so.*'):
            res = glob.glob(os.path.join(sysroot, 'lib*', ld_glob_pattern))
            self.log.debug("Paths for ELF interpreter via '%s' pattern: %s", ld_glob_pattern, res

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
        else:
            return elf_interp

    def _determine_extra_rpaths(self, add_library_path_to_rpath, add_sysroot_libdirs_to_rpath)
        """
        Determine the additional paths to be added to the RPATH and return these as a list
        """
        # TODO: make sure this function ignores anything in filter_rpath_sanity_libs
        extra_rpaths = []
        extra_rpaths_from_option = self.cfg.get('extra_rpaths', None):
        if extra_rpaths_from_option:
            # Replace any $EBROOT* variables by their value
            pattern = r"(\$EBROOT[^/]+)(.*)"
            
            # Modify the list in place
            for i, path in enumerate(extra_rpaths_from_option):
                match = re.match(pattern, path)
                if match:
                    env_var = match.group(1) 
                    rest_of_path = match.group(2)
                    env_value = os.environ.get(env_var, None)
                    if env_value is None:
                        raise EasyBuildError("An environment variable '%s' was used in the 'extra_rpaths' option, "
                                             "but could not be resolved because it was not found in the environment ",
                                             env_var)
                    # Only replace the $EBROOT* part, keep the rest
                    extra_rpaths_from_option[i] = env_value + rest_of_path

            extra_rpaths += extra_rpaths_from_option

        # Then, add paths from LIBRARY_PATH to the extra RPATH
        if add_library_path_to_rpath:
            # Get LIBRARY_PATH as a list and add it to the extra paths to be added to RPATH
            library_path = os.environ.get('LIBRARY_PATH', '').split(':')
            if library_path:
                self.log.info("List of library paths from LIBRARY_PATH to be added to RPATH section: %s", library_path)
                extra_rpaths += library_path

        # Then, add paths from sysroot to the extra RPATH
        if add_sysroot_libdirs_to_rpath:
            if sysroot and self.toolchain.use_rpath:
            sysroot_lib_paths = glob.glob(os.path.join(sysroot, 'lib*'))
            sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*'))
            sysroot_lib_paths += glob.glob(os.path.join(sysroot, 'usr', 'lib*', 'gcc', '*', '*'))
            if sysroot_lib_paths:
                self.log.info("List of library paths in %s to add to RPATH section: %s", sysroot, sysroot_lib_paths)
                extra_rpaths += sysroot_lib_paths

    def post_install_step(self):
        """
        - Copy installation to actual installation directory in case of a staged installation
        - If using sysroot: ensure correct interpreter is used and (if also using RPATH) ensure
        - If using RPATH support: ensure relevant paths from LIBRARY_PATH are added to RPATH
        that the libdirs from the system are added to the RPATH
        """
        # Copy to installdir for staged install
        if self.cfg.get('staged_install', False):
            staged_installdir = self.installdir
            self.installdir = self.actual_installdir
            try:
                # copytree expects target directory to not exist yet
                if os.path.exists(self.installdir):
                    remove_dir(self.installdir)
                shutil.copytree(staged_installdir, self.installdir)
            except OSError as err:
                raise EasyBuildError("Failed to move staged install from %s to %s: %s",
                                     staged_installdir, self.installdir, err)


        # Check for patchelf if we plan to patch either rpath or interpreter
        sysroot = build_option('sysroot')
        add_library_path_to_rpath = self.toolchain.use_rpath and self.cfg.get('patch_rpath', False)
        add_sysroot_libdirs_to_rpath = sysroot and self.cfg.get('patch_rpath', False)
        patch_interpreter = sysroot and self.cfg.get('patch_interpreter', False)
        if add_library_path_to_rpath or add_sysroot_libdirs_to_rpath or patch_interpreter:
            # Fail early if patchelf isn't found - we need it
            if not which('patchelf'):
                error_msg = "patchelf not found via $PATH, required to patch RPATH section in binaries/libraries"
                raise EasyBuildError(error_msg)

        # Get ELF interpreter
        if patch_interpreter:
            elf_interp = _get_elf_interpreter_from_sysroot()

        # Determine the paths needed to be added to RPATH
        if add_library_path_to_rpath or add_sysroot_libdirs_to_rpath:
            extra_rpaths = _determine_extra_rpaths(add_library_path_to_rpath, add_sysroot_libdirs_to_rpath)

        # Get directories to loop over for patching files
        if rpath_dirs is None:
            rpath_dirs = self.cfg['bin_lib_subdirs'] or self.bin_lib_subdirs()

        if not rpath_dirs:
            rpath_dirs = EasyBlock.DEFAULT_BIN_LIB_SUBDIRS
            self.log.info("Using default subdirectories for binaries/libraries to verify RPATH linking: %s",
                          rpath_dirs)
        else:
            self.log.info("Using specified subdirectories for binaries/libraries to verify RPATH linking: %s",
                          rpath_dirs)

        # Loop over all dirs in bin_lib_subdirs to patch all dynamically linked files
        try:
            for dirpath in [os.path.join(self.installdir, d) for d in rpath_dirs]:
                if os.path.exists(dirpath):
                    self.log.debug("Patching ELF headers for files in %s", dirpath)

                    for path in [os.path.join(dirpath, x) for x in os.listdir(dirpath)]:
                        out, _ = run_cmd("file %s" % path, trace=False)
                        if "dynamically linked" in out:
                            # Set ELF interpreter if needed
                            if patch_interpreter and "executable" in out:
                                out, _ = run_cmd("patchelf --print-interpreter %s" % path, trace=False)
                                self.log.debug("ELF interpreter for %s: %s" % (path, out))

                                run_cmd("patchelf --set-interpreter %s %s" % (elf_interp, path), trace=False)

                                out, _ = run_cmd("patchelf --print-interpreter %s" % path, trace=False)
                                self.log.debug("ELF interpreter for %s: %s" % (path, out))

                            # Add to RPATH if needed
                            if extra_rpaths:
                                out, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
                                curr_rpath = out.strip()
                                self.log.debug("RPATH for %s: %s" % (path, curr_rpath))

                                new_rpath = ':'.join([curr_rpath] + extra_rpaths)
                                # note: it's important to wrap the new RPATH value in single quotes,
                                # to avoid magic values like $ORIGIN being resolved by the shell
                                run_cmd("patchelf --force-rpath --set-rpath '%s' %s" % (new_rpath, path), trace=False)

                                curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
                                self.log.debug("RPATH for %s (prior to shrinking): %s" % (path, curr_rpath))

                                run_cmd("patchelf --force-rpath --shrink-rpath %s" % path, trace=False)

                                curr_rpath, _ = run_cmd("patchelf --print-rpath %s" % path, simple=False, trace=False)
                                self.log.debug("RPATH for %s (after shrinking): %s" % (path, curr_rpath))
                                # TODO: make sure that after the shrink _SOME_ RPATH is left, otherwise the sanity check complains

        except OSError as err:
            raise EasyBuildError("Failed to patch RPATH or ELF interpreter section in binaries: %s", err)

        super(Binary, self).post_install_step()

    def sanity_check_rpath(self):
        """Skip the rpath sanity check, this is binary software"""
        if self.cfg.get('run_rpath_sanity_check', False):
            return super(Binary, self).sanity_check_rpath()
        else:
            self.log.info("RPATH sanity check is skipped when using %s easyblock (derived from Binary)"
                          " and run_rpath_sanity_check is False",
                          self.__class__.__name__)

    def make_module_extra(self):
        """Add the specified directories to the PATH."""

        txt = super(Binary, self).make_module_extra()
        prepend_to_path = self.cfg.get('prepend_to_path', PREPEND_TO_PATH_DEFAULT)
        if prepend_to_path:
            txt += self.module_generator.prepend_paths("PATH", prepend_to_path)
        self.log.debug("make_module_extra added this: %s" % txt)
        return txt
