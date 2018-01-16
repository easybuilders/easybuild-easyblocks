##
# Copyright 2015-2018 Ghent University
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
EasyBuild support for using (already installed/existing) system compiler instead of a full install via EasyBuild.

@author Bernd Mohr (Juelich Supercomputing Centre)
@author Kenneth Hoste (Ghent University)
@author Alan O'Cais (Juelich Supercomputing Centre)
"""
import os
import re
from vsc.utils import fancylogger
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.easyblocks.icc import EB_icc
from easybuild.easyblocks.ifort import EB_ifort
from easybuild.easyblocks.gcc import EB_GCC
from easybuild.framework.easyconfig.easyconfig import ActiveMNS
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.filetools import read_file, resolve_path, which
from easybuild.tools.run import run_cmd

_log = fancylogger.getLogger('easyblocks.generic.systemcompiler')

def extract_compiler_version(compiler_name):
    """Extract compiler version for provided compiler_name."""
    # look for 3-4 digit version number, surrounded by spaces
    # examples:
    # gcc (GCC) 4.4.7 20120313 (Red Hat 4.4.7-11)
    # Intel(R) C Intel(R) 64 Compiler XE for applications running on Intel(R) 64, Version 15.0.1.133 Build 20141023
    version_regex = re.compile(r'\s([0-9]+(?:\.[0-9]+){1,3})\s', re.M)
    if compiler_name == 'gcc':
        out, _ = run_cmd("gcc --version", simple=False)
        res = version_regex.search(out)
        if res is None:
            raise EasyBuildError("Could not extract GCC version from %s", out)
        compiler_version = res.group(1)
    elif compiler_name in ['icc', 'ifort']:
        # A fully resolved icc/ifort (without symlinks) includes the release version in the path
        # e.g. .../composer_xe_2015.3.187/bin/intel64/icc
        # Match the last incidence of _ since we don't know what might be in the path, then split it up on /
        compiler_path = which(compiler_name)
        if compiler_path:
            compiler_version = resolve_path(compiler_path).split('_')[-1].split('/')[0]
        else:
            raise EasyBuildError("Compiler command '%s' not found", compiler_name)
        # Check what we have looks like a version number (the regex we use requires spaces around the version number)
        if version_regex.search(' ' + compiler_version + ' ') is None:
            error_msg = "Derived Intel compiler version '%s' doesn't look correct, " % compiler_version
            error_msg += "is compiler installed in a path like '.../composer_xe_2015.3.187/bin/intel64/icc'?"
            raise EasyBuildError(error_msg)
    else:
        raise EasyBuildError("Unknown compiler %s", compiler_name)

    if compiler_version:
        _log.debug("Extracted compiler version '%s' for %s", compiler_version, compiler_name)
    else:
        raise EasyBuildError("Failed to extract compiler version for %s using regex pattern '%s' from: %s",
                             compiler_name, version_regex.pattern, out)

    return compiler_version

# No need to inherit from EB_icc since EB_ifort already inherits from that
class SystemCompiler(Bundle, EB_GCC, EB_ifort):
    """
    Support for generating a module file for the system compiler with specified name.

    The compiler is expected to be available in $PATH, required libraries are assumed to be readily available.

    Specifying 'system' as a version leads to using the derived compiler version in the generated module;
    if an actual version is specified, it is checked against the derived version of the system compiler that was found.
    """

    @staticmethod
    def extra_options():
        """Add custom easyconfig parameters for SystemCompiler easyblock."""
        # Gather extra_vars from inherited classes, order matters here to make this work without problems in __init__
        extra_vars = EB_GCC.extra_options()
        extra_vars.update(EB_icc.extra_options())
        extra_vars.update(EB_ifort.extra_options())
        extra_vars.update(Bundle.extra_options())
        # Add an option to add all module path extensions to the resultant easyconfig
        # This is useful if you are importing a compiler from a non-default path
        extra_vars.update({
            'generate_standalone_module': [
                False,
                "Add known path/library extensions and environment variables for the compiler to the final module",
                CUSTOM
            ],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Extra initialization: keep track of values that may change due to modifications to the version."""
        super(SystemCompiler, self).__init__(*args, **kwargs)

        # Keep track of original values of vars that are subject to change, for restoring later.
        # The version is determined/matched from the installation and the installdir is determined from the system
        # (the original is used to store the EB logs)
        self.orig_version = self.cfg['version']
        self.orig_installdir = self.installdir

    def prepare_step(self, *args, **kwargs):
        """Do compiler appropriate prepare step, determine system compiler version and prefix."""
        if self.cfg['generate_standalone_module']:
            if self.cfg['name'] in ['GCC', 'GCCcore']:
                EB_GCC.prepare_step(self, *args, **kwargs)
            elif self.cfg['name'] in ['icc']:
                EB_icc.prepare_step(self, *args, **kwargs)
            elif self.cfg['name'] in ['ifort']:
                EB_ifort.prepare_step(self, *args, **kwargs)
            else:
                raise EasyBuildError("I don't know how to do the prepare_step for %s", self.cfg['name'])
        else:
            Bundle.prepare_step(self, *args, **kwargs)
            
        # Determine compiler path (real path, with resolved symlinks)
        compiler_name = self.cfg['name'].lower()
        if compiler_name == 'gcccore':
            compiler_name = 'gcc'
        path_to_compiler = which(compiler_name)
        if path_to_compiler:
            path_to_compiler = resolve_path(path_to_compiler)
            self.log.info("Found path to compiler '%s' (with symlinks resolved): %s", compiler_name, path_to_compiler)
        else:
            raise EasyBuildError("%s not found in $PATH", compiler_name)

        # Determine compiler version
        self.compiler_version = extract_compiler_version(compiler_name)

        # Determine installation prefix
        if compiler_name == 'gcc':
            # strip off 'bin/gcc'
            self.compiler_prefix = os.path.dirname(os.path.dirname(path_to_compiler))

        elif compiler_name in ['icc', 'ifort']:
            intelvars_fn = path_to_compiler + 'vars.sh'
            if os.path.isfile(intelvars_fn):
                self.log.debug("Trying to determine compiler install prefix from %s", intelvars_fn)
                intelvars_txt = read_file(intelvars_fn)
                prod_dir_regex = re.compile(r'^PROD_DIR=(.*)$', re.M)
                res = prod_dir_regex.search(intelvars_txt)
                if res:
                    self.compiler_prefix = res.group(1)
                else:
                    raise EasyBuildError("Failed to determine %s installation prefix from %s",
                                          compiler_name, intelvars_fn)
            else:
                # strip off 'bin/intel*/icc'
                self.compiler_prefix = os.path.dirname(os.path.dirname(os.path.dirname(path_to_compiler)))

            # For versions 2016+ of Intel compilers they changed the installation path so must shave off 2 more
            # directories from result of the above
            if LooseVersion(self.compiler_version) >= LooseVersion('2016'):
                self.compiler_prefix = os.path.dirname(os.path.dirname(self.compiler_prefix))

        else:
            raise EasyBuildError("Unknown system compiler %s" % self.cfg['name'])

        if not os.path.exists(self.compiler_prefix):
            raise EasyBuildError("Path derived for system compiler (%s) does not exist: %s!",
                                 compiler_name, self.compiler_prefix)
        self.log.debug("Derived version/install prefix for system compiler %s: %s, %s",
                       compiler_name, self.compiler_version, self.compiler_prefix)

        # If EasyConfig specified "real" version (not 'system' which means 'derive automatically'), check it
        if self.cfg['version'] == 'system':
            self.log.info("Found specified version '%s', going with derived compiler version '%s'",
                          self.cfg['version'], self.compiler_version)
        elif self.cfg['version'] != self.compiler_version:
            raise EasyBuildError("Specified version (%s) does not match version reported by compiler (%s)" %
                                 (self.cfg['version'], self.compiler_version))

    def make_installdir(self, dontcreate=None):
        """Custom implementation of make installdir: do nothing, do not touch system compiler directories and files."""
        pass

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.  Return known dict for the system compiler, or empty dict if
        generate_standalone_module parameter is False
        """
        guesses = {}
        if self.cfg['generate_standalone_module']:
            if self.compiler_prefix in ['/usr', '/usr/local']:
                # Force off adding paths to module since unloading such a module would be a potential shell killer
                print_warning("Ignoring option 'generate_standalone_module' since installation prefix is %s",
                              self.compiler_prefix)
            else:
                if self.cfg['name'] in ['GCC','GCCcore']:
                    guesses = EB_GCC.make_module_req_guess(self)
                elif self.cfg['name'] in ['icc']:
                    guesses = EB_icc.make_module_req_guess(self)
                elif self.cfg['name'] in ['ifort']:
                    guesses = EB_ifort.make_module_req_guess(self)
                else:
                    raise EasyBuildError("I don't know how to generate module var guesses for %s", self.cfg['name'])
        return guesses

    def make_module_step(self, fake=False):
        """
        Custom module step for SystemCompiler: make 'EBROOT' and 'EBVERSION' reflect actual system compiler version
        and install path.
        """
        # For module file generation: temporarly set version and installdir to system compiler values
        self.cfg['version'] = self.compiler_version
        self.installdir = self.compiler_prefix

        # Generate module
        res = super(SystemCompiler, self).make_module_step(fake=fake)

        # Reset version and installdir to EasyBuild values
        self.installdir = self.orig_installdir
        self.cfg['version'] = self.orig_version
        return res

    def make_module_extend_modpath(self):
        """
        Custom prepend-path statements for extending $MODULEPATH: use version specified in easyconfig file (e.g.,
        "system") rather than the actual version (e.g., "4.8.2").
        """
        # temporarly set switch back to version specified in easyconfig file (e.g., "system")
        self.cfg['version'] = self.orig_version

        # Retrieve module path extensions
        res = super(SystemCompiler, self).make_module_extend_modpath()

        # Reset to actual compiler version (e.g., "4.8.2")
        self.cfg['version'] = self.compiler_version
        return res

    def make_module_extra(self, *args, **kwargs):
        """Add any additional module text."""
        if self.cfg['generate_standalone_module']:
            if self.cfg['name'] in ['GCC','GCCcore']:
                extras = EB_GCC.make_module_extra(self, *args, **kwargs)
            elif self.cfg['name'] in ['icc']:
                extras = EB_icc.make_module_extra(self, *args, **kwargs)
            elif self.cfg['name'] in ['ifort']:
                extras = EB_ifort.make_module_extra(self, *args, **kwargs)
            else:
                raise EasyBuildError("I don't know how to generate extra module text for %s", self.cfg['name'])
        else:
            extras = super(SystemCompiler, self).make_module_extra(*args, **kwargs)
        return extras

    def post_install_step(self, *args, **kwargs):
        """Do nothing."""
        pass

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
