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
EasyBuild support for installing compiler toolchains, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.toolchain.toolchain import env_vars_external_module


class Toolchain(Bundle):
    """Compiler toolchain easyblock: nothing to install, just generate module file."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to toolchains."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'set_env_external_modules': [False, "Include setenv statements for toolchain components that use "
                                                "an external module, based on available metadata", CUSTOM],
        })
        return Bundle.extra_options(extra_vars=extra_vars)

    def make_module_extra(self):
        """
        Define $EBROOT* and $EBVERSION* environment for toolchain components marked as external module,
        if corresponding metadata is available.
        """
        txt = super(Toolchain, self).make_module_extra()

        # include $EBROOT* and $EBVERSION* definitions for toolchain components marked as external modules (if any)
        # in the generated module file for this toolchain;
        # this is required to let the EasyBuild framework set up the build environment based on the toolchain
        if self.cfg.get('set_env_external_modules', False):
            for dep in [d for d in self.cfg['dependencies'] if d['external_module']]:

                mod_name = dep['full_mod_name']
                metadata = dep['external_module_metadata']
                names, versions = metadata.get('name', []), metadata.get('version')

                # if no versions are available, use None as version (for every software name)
                if versions is None:
                    versions = [None] * len(names)

                if names:
                    self.log.info("Adding environment variables for %s provided by external module %s", names, mod_name)

                    for name, version in zip(names, versions):
                        env_vars = env_vars_external_module(name, version, metadata)
                        for key in env_vars:
                            self.log.info("Defining $%s for external module %s: %s", key, mod_name, env_vars[key])
                            txt += self.module_generator.set_environment(key, env_vars[key])

        return txt
