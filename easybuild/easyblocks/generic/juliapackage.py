##
# Copyright 2022-2024 Vrije Universiteit Brussel
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
EasyBuild support for Julia Packages, implemented as an easyblock

@author: Alex Domingo (Vrije Universiteit Brussel)
"""
import os
import re

from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.filetools import copy_dir
from easybuild.tools.run import run_cmd

EXTS_FILTER_JULIA_PACKAGES = ("julia -e 'using %(ext_name)s'", "")
USER_DEPOT_PATTERN = re.compile(r"\/\.julia\/?$")


class JuliaPackage(ExtensionEasyBlock):
    """Builds and installs Julia Packages."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to JuliaPackage."""
        extra_vars = ExtensionEasyBlock.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'download_pkg_deps': [
                False, "Let Julia download and bundle all needed dependencies for this installation", CUSTOM
            ],
        })
        return extra_vars

    def set_depot_path(self):
        """
        Top directory in JULIA_DEPOT_PATH is target installation directory
        Prepend installation directory to JULIA_DEPOT_PATH
        Remove user depot from JULIA_DEPOT_PATH during installation
        see https://docs.julialang.org/en/v1/manual/environment-variables/#JULIA_DEPOT_PATH
        """
        depot_path = os.getenv('JULIA_DEPOT_PATH', [])

        if depot_path:
            depot_path = depot_path.split(os.pathsep)
        if len(depot_path) > 0:
            # strip user depot path (top entry by definition)
            if USER_DEPOT_PATTERN.search(depot_path[0]):
                self.log.debug('Temporary disabling Julia user depot: %s', depot_path[0])
                del depot_path[0]

        depot_path.insert(0, self.installdir)
        env.setvar('JULIA_DEPOT_PATH', os.pathsep.join(depot_path))

    def set_pkg_offline(self):
        """Enable offline mode of Julia Pkg"""
        if get_software_root('Julia') is None:
            raise EasyBuildError("Julia not included as dependency!")

        if not self.cfg['download_pkg_deps']:
            julia_version = get_software_version('Julia')
            if LooseVersion(julia_version) >= LooseVersion('1.5'):
                # Enable offline mode of Julia Pkg
                # https://pkgdocs.julialang.org/v1/api/#Pkg.offline
                env.setvar('JULIA_PKG_OFFLINE', 'true')
            else:
                errmsg = (
                    "Cannot set offline mode in Julia v%s (needs Julia >= 1.5). "
                    "Enable easyconfig option 'download_pkg_deps' to allow installation "
                    "with any extra downloaded dependencies."
                )
                raise EasyBuildError(errmsg, julia_version)

    def prepare_step(self, *args, **kwargs):
        """Prepare for installing Julia package."""
        super(JuliaPackage, self).prepare_step(*args, **kwargs)
        self.set_pkg_offline()
        self.set_depot_path()

    def configure_step(self):
        """No separate configuration for JuliaPackage."""
        pass

    def build_step(self):
        """No separate build procedure for JuliaPackage."""
        pass

    def test_step(self):
        """No separate (standard) test procedure for JuliaPackage."""
        pass

    def install_step(self):
        """Install Julia package with Pkg"""

        # command sequence for Julia.Pkg
        julia_pkg_cmd = ['using Pkg']
        if os.path.isdir(os.path.join(self.start_dir, '.git')):
            # sources from git repos can be installed as any remote package
            self.log.debug('Installing Julia package in normal mode (Pkg.add)')

            julia_pkg_cmd.extend([
                # install package from local path preserving existing dependencies
                'Pkg.add(url="%s"; preserve=Pkg.PRESERVE_ALL)' % self.start_dir,
            ])
        else:
            # plain sources have to be installed in develop mode
            # copy sources to install directory and install
            self.log.debug('Installing Julia package in develop mode (Pkg.develop)')

            install_pkg_path = os.path.join(self.installdir, 'packages', self.name)
            copy_dir(self.start_dir, install_pkg_path)

            julia_pkg_cmd.extend([
                'Pkg.develop(PackageSpec(path="%s"))' % install_pkg_path,
                'Pkg.build("%s")' % self.name,
            ])

        julia_pkg_cmd = ';'.join(julia_pkg_cmd)
        cmd = ' '.join([
            self.cfg['preinstallopts'],
            "julia -e '%s'" % julia_pkg_cmd,
            self.cfg['installopts'],
        ])
        (out, _) = run_cmd(cmd, log_all=True, simple=False)

        return out

    def run(self):
        """Install Julia package as an extension."""

        if not self.src:
            errmsg = "No source found for Julia package %s, required for installation. (src: %s)"
            raise EasyBuildError(errmsg, self.name, self.src)
        ExtensionEasyBlock.run(self, unpack_src=True)

        self.set_pkg_offline()
        self.set_depot_path()  # all extensions share common depot in installdir
        self.install_step()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for JuliaPackage"""

        pkg_dir = os.path.join('packages', self.name)

        custom_paths = {
            'files': [],
            'dirs': [pkg_dir],
        }
        kwargs.update({'custom_paths': custom_paths})

        return ExtensionEasyBlock.sanity_check_step(self, EXTS_FILTER_JULIA_PACKAGES, *args, **kwargs)

    def make_module_extra(self):
        """
        Module has to append installation directory to JULIA_DEPOT_PATH to keep
        the user depot in the top entry. See issue easybuilders/easybuild-easyconfigs#17455
        """
        txt = super(JuliaPackage, self).make_module_extra()
        txt += self.module_generator.append_paths('JULIA_DEPOT_PATH', [''])
        return txt
