##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for SLEPc, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
@author: Alex Domingo (Vrije Universiteit Brussel)
"""

import os
import re
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import BUILD, CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_SLEPc(ConfigureMake):
    """Support for building and installing SLEPc"""

    @staticmethod
    def extra_options():
        """Add extra config options specific to SLEPc."""
        extra_vars = {
            'runtest': ['test', "Make target to test build", BUILD],
            'petsc_arch': [None, "PETSc architecture to use (value for $PETSC_ARCH)", CUSTOM],
            'sourceinstall': [False, "Indicates whether a source installation should be performed", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize SLEPc custom variables."""
        super(EB_SLEPc, self).__init__(*args, **kwargs)

        if self.cfg['sourceinstall']:
            self.build_in_installdir = True

    def prepare_step(self, *args, **kwargs):
        """Prepare build environment."""
        super(EB_SLEPc, self).prepare_step(*args, **kwargs)

        # PETSc installed in 'sourceinstall' mode defines $PETSC_ARCH
        self.petsc_arch = os.environ.get('PETSC_ARCH', '')
        if self.cfg['sourceinstall'] and self.cfg['petsc_arch'] is not None:
            if self.petsc_arch:
                # $PETSC_ARCH defined by PETSc has precedence, changing it will break the installation
                print_warning(
                    f"Ignoring easyconfig parameter 'petsc_arch={self.cfg['petsc_arch']}' of {self.name} "
                    f"as it differs to '$PETSC_ARCH={self.petsc_arch}' defined by its PETSc dependency"
                )
            else:
                # SLEPc installs with 'sourceinstall' on top of regular installs
                # of PETSc (without $PETSC_ARCH) can define custom PETSC_ARCH
                self.petsc_arch = self.cfg['petsc_arch']

        self.slepc_subdir = ''
        if self.cfg['sourceinstall']:
            self.slepc_subdir = os.path.join(f'{self.name.lower()}-{self.version}', self.petsc_arch)

        # specify correct LD_LIBRARY_PATH and CPATH for SLEPc installation
        self.module_load_environment.LD_LIBRARY_PATH = [os.path.join(self.slepc_subdir, "lib")]
        self.module_load_environment.set_alias_vars(
            MODULE_LOAD_ENV_HEADERS,
            [os.path.join(self.slepc_subdir, "include")],
        )

    def configure_step(self):
        """Configure SLEPc by setting configure options and running configure script."""

        # check PETSc dependency
        petsc_dir = get_software_root("PETSc")
        if not petsc_dir:
            raise EasyBuildError("PETSc module not loaded?")

        # set SLEPC_DIR for configure (env) and build_step
        slepc_dir = self.cfg['start_dir'].rstrip(os.path.sep)
        env.setvar('SLEPC_DIR', slepc_dir)
        self.cfg.update('buildopts', "SLEPC_DIR='%s'" % slepc_dir)
        self.cfg.update('buildopts', "PETSC_DIR='%s'" % petsc_dir)  # Env variable is set by module

        # optional dependencies
        dep_filter = [d['name'] for d in self.cfg.builddependencies()] + ['PETSc', 'Python']
        deps = [dep['name'] for dep in self.cfg.dependencies() if dep['name'] not in dep_filter]
        for dep in deps:
            deproot = get_software_root(dep)
            if deproot:
                withdep = "--with-%s" % dep.lower()
                self.cfg.update('configopts', '%s=1 %s-dir=%s' % (withdep, withdep, deproot))

        if self.cfg['sourceinstall']:
            # run configure without --prefix (required)
            cmd = "%s ./configure %s" % (self.cfg['preconfigopts'], self.cfg['configopts'])
            res = run_shell_cmd(cmd)
            out = res.output
        else:
            # regular './configure --prefix=X' for non-source install
            # make sure old install dir is removed first
            self.make_installdir(dontcreate=True)
            out = super(EB_SLEPc, self).configure_step()

        # check for errors in configure
        error_regexp = re.compile("ERROR")
        if error_regexp.search(out):
            raise EasyBuildError("Error(s) detected in configure output!")

        # SLEPc > 3.5, make does not accept -j
        if LooseVersion(self.version) >= LooseVersion("3.5"):
            self.cfg.parallel = 1

    def install_step(self):
        """
        Install using make install (for non-source installations)
        """
        if not self.cfg['sourceinstall']:
            super(EB_SLEPc, self).install_step()

    def make_module_extra(self):
        """Set SLEPc specific environment variables (SLEPC_DIR)."""
        txt = super(EB_SLEPc, self).make_module_extra()

        if self.cfg['sourceinstall']:
            subdir = '%s-%s' % (self.name.lower(), self.version)
            txt += self.module_generator.set_environment('SLEPC_DIR', os.path.join(self.installdir, subdir))

        else:
            txt += self.module_generator.set_environment('SLEPC_DIR', self.installdir)

        return txt

    def sanity_check_step(self):
        """Custom sanity check for SLEPc"""
        custom_paths = {
            'files': [os.path.join(self.slepc_subdir, 'lib', f'libslepc.{get_shared_lib_ext()}')],
            'dirs': [
                os.path.join(self.slepc_subdir, 'include'),
                os.path.join(self.slepc_subdir, 'lib'),
                os.path.join(self.slepc_subdir, 'lib', 'slepc', 'conf'),
            ],
        }
        super(EB_SLEPc, self).sanity_check_step(custom_paths=custom_paths)
