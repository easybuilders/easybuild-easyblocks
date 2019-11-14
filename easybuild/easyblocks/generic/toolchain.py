##
# Copyright 2009-2019 Ghent University
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
import os

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.tools.modules import get_software_root_env_var_name, get_software_version_env_var_name


class Toolchain(Bundle):
    """
    Compiler toolchain: generate module file only, nothing to build/install
    """
    def make_module_extra(self):
        """
        Define $EBROOT* and $EBVERSION* environment for toolchain components marked as external module,
        if corresponding metadata is available.
        """
        txt = super(Toolchain, self).make_module_extra()

        # include $EBROOT* and $EBVERSION* definitions for toolchain components marked as external modules (if any)
        # in the generated module file for this toolchain;
        # this is required to let the EasyBuild framework set up the build environment based on the toolchain
        for dep in [d for d in self.cfg['dependencies'] if d['external_module']]:

            mod_name = dep['full_mod_name']
            metadata = dep['external_module_metadata']
            names, versions, prefix = metadata.get('name'), metadata.get('version'), metadata.get('prefix')

            if names:
                self.log.info("Adding environment variables for %s provided by external module %s", names, mod_name)

                # define $EBVERSION* if version is available
                print mod_name, versions
                if versions:
                    for name, version in zip(names, versions):
                        env_var = get_software_version_env_var_name(name)
                        self.log.info("Defining $%s for external module %s: %s", env_var, mod_name, version)
                        txt += self.module_generator.set_environment(env_var, version)

                # define $EBROOT* if prefix is available
                if prefix:
                    # prefix can be specified via environment variable (+ subdir) or absolute path
                    prefix_parts = prefix.split(os.path.sep)
                    if prefix_parts[0] in os.environ:
                        env_var = prefix_parts[0]
                        prefix_path = os.environ[env_var]
                        rel_path = os.path.sep.join(prefix_parts[1:])
                        if rel_path:
                            prefix_path = os.path.join(prefix_path, rel_path, '')

                        self.log.debug("Derived prefix for software named %s from $%s (rel path: %s): %s",
                                    name, env_var, rel_path, prefix_path)
                    else:
                        prefix_path = prefix
                        self.log.debug("Using specified path as prefix for software named %s: %s", name, prefix_path)

                    for name in names:
                        env_var = get_software_root_env_var_name(name)
                        self.log.info("Defining $%s for external module %s: %s", env_var, mod_name, prefix_path)
                        txt += self.module_generator.set_environment(env_var, prefix_path)

        return txt
