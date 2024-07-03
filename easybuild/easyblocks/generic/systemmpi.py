##
# Copyright 2015-2024 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for using (already installed/existing) system MPI instead of a full install via EasyBuild.

@author Alan O'Cais (Juelich Supercomputing Centre)
"""
import os
import re

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.systemcompiler import extract_compiler_version
from easybuild.easyblocks.impi import EB_impi
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import read_file, resolve_path, which
from easybuild.tools.modules import get_software_version
from easybuild.tools.run import run_cmd


class SystemMPI(Bundle, ConfigureMake, EB_impi):
    """
    Support for generating a module file for the system mpi with specified name.

    The mpi compiler is expected to be available in $PATH, required libraries are assumed to be readily available.

    Specifying 'system' as a version leads to using the derived mpi version in the generated module;
    if an actual version is specified, it is checked against the derived version of the system mpi that was found.
    """

    @staticmethod
    def extra_options():
        """Add custom easyconfig parameters for SystemMPI easyblock."""
        # Gather extra_vars from inherited classes, order matters to make sure bundle initialises correctly
        extra_vars = ConfigureMake.extra_options()
        extra_vars.update(EB_impi.extra_options())
        extra_vars.update(Bundle.extra_options())
        # Add an option to add all module path extensions to the resultant easyconfig
        # This is useful if you are importing the MPI installation from a non-default path
        extra_vars.update({
            'generate_standalone_module': [False, "Add known path extensions and environment variables for the MPI "
                                                  "installation to the final module", CUSTOM],
        })
        return extra_vars

    def extract_ompi_setting(self, pattern, txt):
        """Extract a particular OpenMPI setting from provided string."""

        version_regex = re.compile(r'^\s+%s: (.*)$' % pattern, re.M)
        res = version_regex.search(txt)
        if res:
            setting = res.group(1)
            self.log.debug("Extracted OpenMPI setting %s: '%s' from search text", pattern, setting)
        else:
            raise EasyBuildError("Failed to extract OpenMPI setting '%s' using regex pattern '%s' from: %s",
                                 pattern, version_regex.pattern, txt)

        return setting

    def __init__(self, *args, **kwargs):
        """Extra initialization: keep track of values that may change due to modifications to the version."""
        super(SystemMPI, self).__init__(*args, **kwargs)

        # Keep track of original values of vars that are subject to change, for restoring later.
        # The version is determined/matched from the installation and the installdir is determined from the system
        # (the original is used to store the EB logs)
        self.orig_version = self.cfg['version']
        self.orig_installdir = self.installdir

    def prepare_step(self, *args, **kwargs):
        """Load all dependencies, determine system MPI version, prefix and any associated envvars."""

        # Do the bundle prepare step to ensure any deps are loaded (no need to worry about licences for Intel MPI)
        Bundle.prepare_step(self, *args, **kwargs)

        # Prepare additional parameters: determine system MPI version, prefix and any associated envvars.
        mpi_name = self.cfg['name'].lower()

        # Determine MPI wrapper path (real path, with resolved symlinks) to ensure it exists
        if mpi_name == 'impi':
            # For impi the version information is only found in *some* of the wrappers it ships, in particular it is
            # not in mpicc
            mpi_c_wrapper = 'mpiicc'
            path_to_mpi_c_wrapper = which(mpi_c_wrapper)
            if not path_to_mpi_c_wrapper:
                mpi_c_wrapper = 'mpigcc'
                path_to_mpi_c_wrapper = which(mpi_c_wrapper)
                if not path_to_mpi_c_wrapper:
                    raise EasyBuildError("Could not find suitable MPI wrapper to extract version for impi")
        else:
            mpi_c_wrapper = 'mpicc'
            path_to_mpi_c_wrapper = which(mpi_c_wrapper)

        if path_to_mpi_c_wrapper:
            path_to_mpi_c_wrapper = resolve_path(path_to_mpi_c_wrapper)
            self.log.info("Found path to MPI implementation '%s' %s compiler (with symlinks resolved): %s",
                          mpi_name, mpi_c_wrapper, path_to_mpi_c_wrapper)
        else:
            raise EasyBuildError("%s not found in $PATH", mpi_c_wrapper)

        # Determine MPI version, installation prefix and underlying compiler
        if mpi_name in ('openmpi', 'spectrummpi'):
            # Spectrum MPI is based on Open MPI so is also covered by this logic
            output_of_ompi_info, _ = run_cmd("ompi_info", simple=False)

            # Extract the version of the MPI implementation
            if mpi_name == 'spectrummpi':
                mpi_version_string = 'Spectrum MPI'
            else:
                mpi_version_string = 'Open MPI'
            self.mpi_version = self.extract_ompi_setting(mpi_version_string, output_of_ompi_info)

            # Extract the installation prefix
            self.mpi_prefix = self.extract_ompi_setting("Prefix", output_of_ompi_info)

            # Extract any OpenMPI environment variables in the current environment and ensure they are added to the
            # final module
            self.mpi_env_vars = dict((key, value) for key, value in os.environ.items() if key.startswith('OMPI_'))

            # Extract the C compiler used underneath the MPI implementation, check for the definition of OMPI_MPICC
            self.mpi_c_compiler = self.extract_ompi_setting("C compiler", output_of_ompi_info)
        elif mpi_name == 'impi':
            # Extract the version of IntelMPI
            # The prefix in the the mpiicc (or mpigcc) script can be used to extract the explicit version
            contents_of_mpixcc = read_file(path_to_mpi_c_wrapper)
            prefix_regex = re.compile(r'(?<=compilers_and_libraries_)(.*)(?=/linux/mpi)', re.M)

            self.mpi_version = None
            res = prefix_regex.search(contents_of_mpixcc)
            if res:
                self.mpi_version = res.group(1)
            else:
                # old iimpi version
                prefix_regex = re.compile(r'^prefix=(.*)$', re.M)
                res = prefix_regex.search(contents_of_mpixcc)
                if res:
                    self.mpi_version = res.group(1).split('/')[-1]

            if self.mpi_version is None:
                raise EasyBuildError("No version found for system Intel MPI")
            else:
                self.log.info("Found Intel MPI version %s for system MPI" % self.mpi_version)

            # Extract the installation prefix, if I_MPI_ROOT is defined, let's use that
            i_mpi_root = os.environ.get('I_MPI_ROOT')
            if i_mpi_root:
                self.mpi_prefix = i_mpi_root
            else:
                # Else just go up three directories from where mpiicc is found
                # (it's 3 because bin64 is a symlink to intel64/bin and we are assuming 64 bit)
                self.mpi_prefix = os.path.dirname(os.path.dirname(os.path.dirname(path_to_mpi_c_wrapper)))

            # Extract any IntelMPI environment variables in the current environment and ensure they are added to the
            # final module
            self.mpi_env_vars = {}
            for key, value in os.environ.items():
                i_mpi_key = key.startswith('I_MPI_') or key.startswith('MPICH_')
                mpi_profile_key = key.startswith('MPI') and key.endswith('PROFILE')
                if i_mpi_key or mpi_profile_key:
                    self.mpi_env_vars[key] = value

            # Extract the C compiler used underneath Intel MPI
            compile_info, exit_code = run_cmd("%s -compile-info" % mpi_c_wrapper, simple=False)
            if exit_code == 0:
                self.mpi_c_compiler = compile_info.split(' ', 1)[0]
            else:
                raise EasyBuildError("Could not determine C compiler underneath Intel MPI, '%s -compiler-info' "
                                     "returned %s", mpi_c_wrapper, compile_info)

        else:
            raise EasyBuildError("Unrecognised system MPI implementation %s", mpi_name)

        # Ensure install path of system MPI actually exists
        if not os.path.exists(self.mpi_prefix):
            raise EasyBuildError("Path derived for system MPI (%s) does not exist: %s!", mpi_name, self.mpi_prefix)

        self.log.debug("Derived version/install prefix for system MPI %s: %s, %s",
                       mpi_name, self.mpi_version, self.mpi_prefix)

        # For the version of the underlying C compiler need to explicitly extract (to be certain)
        self.c_compiler_version = extract_compiler_version(self.mpi_c_compiler)
        self.log.debug("Derived compiler/version for C compiler underneath system MPI %s: %s, %s",
                       mpi_name, self.mpi_c_compiler, self.c_compiler_version)

        # If EasyConfig specified "real" version (not 'system' which means 'derive automatically'), check it
        if self.cfg['version'] == 'system':
            self.log.info("Found specified version '%s', going with derived MPI version '%s'",
                          self.cfg['version'], self.mpi_version)
        elif self.cfg['version'] == self.mpi_version:
            self.log.info("Specified MPI version %s matches found version" % self.mpi_version)
        else:
            raise EasyBuildError("Specified version (%s) does not match version reported by MPI (%s)",
                                 self.cfg['version'], self.mpi_version)

    def make_installdir(self, dontcreate=None):
        """Custom implementation of make installdir: do nothing, do not touch system MPI directories and files."""
        pass

    def post_install_step(self):
        """Do nothing."""
        pass

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.  Return known dict for the system MPI.
        """
        guesses = {}
        if self.cfg['generate_standalone_module']:
            if self.mpi_prefix in ['/usr', '/usr/local']:
                # Force off adding paths to module since unloading such a module would be a potential shell killer
                print_warning("Ignoring option 'generate_standalone_module' since installation prefix is %s",
                              self.mpi_prefix)
            else:
                if self.cfg['name'] in ['OpenMPI', 'SpectrumMPI']:
                    guesses = ConfigureMake.make_module_req_guess(self)
                elif self.cfg['name'] in ['impi']:
                    guesses = EB_impi.make_module_req_guess(self)
                else:
                    raise EasyBuildError("I don't know how to generate module var guesses for %s", self.cfg['name'])
        return guesses

    def make_module_step(self, fake=False):
        """
        Custom module step for SystemMPI: make 'EBROOT' and 'EBVERSION' reflect actual system MPI version
        and install path.
        """
        # First let's verify that the toolchain and the compilers under MPI match
        if self.toolchain.is_system_toolchain():
            # If someone is using system as the MPI toolchain lets assume that gcc is the compiler underneath MPI
            c_compiler_name = 'gcc'
            # Also need to fake the compiler version
            c_compiler_version = self.c_compiler_version
            self.log.info("Found system toolchain so assuming GCC as compiler underneath MPI and faking the version")
        else:
            c_compiler_name = self.toolchain.COMPILER_CC
            c_compiler_version = get_software_version(self.toolchain.COMPILER_MODULE_NAME[0])

        if self.mpi_c_compiler != c_compiler_name or self.c_compiler_version != c_compiler_version:
            raise EasyBuildError("C compiler for toolchain (%s/%s) and underneath MPI (%s/%s) do not match!",
                                 c_compiler_name, c_compiler_version, self.mpi_c_compiler, self.c_compiler_version)

        # For module file generation: temporarily set version and installdir to system MPI values
        self.cfg['version'] = self.mpi_version
        self.installdir = self.mpi_prefix

        # Generate module
        res = super(SystemMPI, self).make_module_step(fake=fake)

        # Reset version and installdir to EasyBuild values
        self.installdir = self.orig_installdir
        self.cfg['version'] = self.orig_version
        return res

    def make_module_extend_modpath(self):
        """
        Custom prepend-path statements for extending $MODULEPATH: use version specified in easyconfig file (e.g.,
        "system") rather than the actual version (e.g., "2.0.2").
        """
        # temporarily set switch back to version specified in easyconfig file (e.g., "system")
        self.cfg['version'] = self.orig_version

        # Retrieve module path extensions
        res = super(SystemMPI, self).make_module_extend_modpath()

        # Reset to actual MPI version (e.g., "2.0.2")
        self.cfg['version'] = self.mpi_version
        return res

    def make_module_extra(self, *args, **kwargs):
        """Add any additional module text."""
        if self.cfg['generate_standalone_module']:
            if self.cfg['name'] in ['OpenMPI', 'SpectrumMPI']:
                extras = ConfigureMake.make_module_extra(self, *args, **kwargs)
            elif self.cfg['name'] in ['impi']:
                extras = EB_impi.make_module_extra(self, *args, **kwargs)
            else:
                raise EasyBuildError("I don't know how to generate extra module text for %s", self.cfg['name'])
            # include environment variables defined for MPI implementation
            for key, val in sorted(self.mpi_env_vars.items()):
                extras += self.module_generator.set_environment(key, val)
            self.log.debug("make_module_extra added this: %s" % extras)
        else:
            extras = super(SystemMPI, self).make_module_extra(*args, **kwargs)
        return extras

    def cleanup_step(self):
        """Do nothing."""
        pass

    def permissions_step(self):
        """Do nothing."""
        pass

    def sanity_check_step(self, *args, **kwargs):
        """
        Nothing is being installed, so just being able to load the (fake) module is sufficient
        """
        self.log.info("Testing loading of module '%s' by means of sanity check" % self.full_mod_name)
        fake_mod_data = self.load_fake_module(purge=True)
        self.log.debug("Cleaning up after testing loading of module")
        self.clean_up_fake_module(fake_mod_data)
