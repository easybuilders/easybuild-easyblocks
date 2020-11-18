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
EasyBuild support for building and installing Julia packages, implemented as an easyblock

@author: Victor Holanda (CSCS)
@author: Samuel Omlin (CSCS)
"""
import os
import shutil
import socket

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.tools.config import build_option
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir
from easybuild.tools.run import run_cmd, parse_log_for_error
from easybuild.tools import systemtools
#from easybuild.easyblocks.generic.pythonpackage import PythonPackage, det_pylibdir
from juliapackage import JuliaPackage


class JuliaBundle(Bundle):
    """
    Install an Julia package as a separate module, or as an extension.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to bundles of Python packages."""
        #50         extra_vars = {
        #51             'arch_name': [None, "Change julia's Project.toml pathname", CUSTOM],
        #52         }
        if extra_vars is None:
            extra_vars = {}
        # combine custom easyconfig parameters of Bundle & PythonPackage
        extra_vars = Bundle.extra_options(extra_vars)
        return JuliaPackage.extra_options(extra_vars)

    def get_environment_folder(self):
        env_path = ''

        hostname = socket.gethostname()
        hostname_short = ''.join(c for c in hostname if not c.isdigit())

        if self.cfg['arch_name']:
            env_path = '-'.join([hostname_short, self.cfg['arch_name']])
            return env_path

        optarch = build_option('optarch') or None
        if optarch:
            env_path = '-'.join([hostname_short, optarch])
        else:
            arch = systemtools.get_cpu_architecture()
            cpu_family = systemtools.get_cpu_family()
            env_path = '-'.join([hostname_short, cpu_family, arch])
        return env_path

    def get_user_depot_path(self):
        user_depot_path = ''

        hostname = socket.gethostname()
        hostname_short = ''.join(c for c in hostname if not c.isdigit())

        optarch = build_option('optarch') or None
        if optarch:
            user_depot_path = os.path.join('~', '.julia', self.version, self.get_environment_folder())
        else:
            arch = systemtools.get_cpu_architecture()
            cpu_family = systemtools.get_cpu_family()
            user_depot_path = os.path.join('~', '.julia', self.version, self.get_environment_folder())
        return user_depot_path

    def __init__(self, *args, **kwargs):
        """Initliaze RPackage-specific class variables."""
        super(JuliaBundle, self).__init__(*args, **kwargs)
        self.cfg['exts_defaultclass'] = 'JuliaPackage'

        # need to disable templating to ensure that actual value for exts_default_options is updated...
        prev_enable_templating = self.cfg.enable_templating
        self.cfg.enable_templating = False

        # set default options for extensions according to relevant top-level easyconfig parameters
        julpkg_keys = JuliaPackage.extra_options().keys()
        for key in julpkg_keys:
            if key not in self.cfg['exts_default_options']:
                self.cfg['exts_default_options'][key] = self.cfg[key]

        self.cfg['exts_default_options']['download_dep_fail'] = True
        self.log.info("Detection of downloaded extension dependencies is enabled")

        self.cfg.enable_templating = prev_enable_templating

        self.log.info("exts_default_options: %s", self.cfg['exts_default_options'])

        self.user_depot = self.get_user_depot_path()
        self.extensions_depot = 'extensions'

        self.admin_load_path = os.path.join(self.extensions_depot, "environments", '-'.join([self.version, self.get_environment_folder()]))
        #self.depot_path = ':'.join([user_depot, extensions_depot])
        # this is very important to remember the addition of the self.verion
        #self.julia_project = os.path.join(user_depot, "environments", '-'.join([self.version, self.get_environment_folder()]))
        #self.julia_load_path = '@:@#.#.#-%s:@stdlib' % self.get_environment_folder()

    def sanity_check_step(self):
        """Custom sanity check for Julia."""

        custom_paths = {
                # extensions/environments/1.0.4-daint-gpu/Manifest.toml
            'files': [],
            'dirs': ['extensions'],
        }
        super(Bundle, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self, *args, **kwargs):
        txt = super(Bundle, self).make_module_extra(*args, **kwargs)

        txt += self.module_generator.prepend_paths('JULIA_DEPOT_PATH', self.extensions_depot)
        txt += self.module_generator.prepend_paths('EBJULIA_ADMIN_DEPOT_PATH', self.extensions_depot)

        txt += self.module_generator.prepend_paths('JULIA_LOAD_PATH', self.admin_load_path)
        txt += self.module_generator.prepend_paths('EBJULIA_ADMIN_LOAD_PATH', self.admin_load_path)

        return txt

