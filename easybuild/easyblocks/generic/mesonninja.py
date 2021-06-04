##
# Copyright 2018-2021 Ghent University
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
EasyBuild support for installing software with Meson & Ninja.

@author: Kenneth Hoste (Ghent University)
"""

from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, create_unused_dir, which
from easybuild.tools.run import run_cmd


class MesonNinja(EasyBlock):
    """
    Support for building and installing software with 'meson' and 'ninja'.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to MesonNinja."""
        extra_vars = EasyBlock.extra_options(extra_vars)
        extra_vars.update({
            'separate_build_dir': [True, "Perform build in a separate directory", CUSTOM],
        })
        return extra_vars

    def configure_step(self, cmd_prefix=''):
        """
        Configure with Meson.
        """
        # make sure both Meson and Ninja are included as build dependencies
        build_dep_names = [d['name'] for d in self.cfg.builddependencies()]
        for tool in ['Ninja', 'Meson']:
            if tool not in build_dep_names:
                raise EasyBuildError("%s not included as build dependency", tool)
            cmd = tool.lower()
            if not which(cmd):
                raise EasyBuildError("'%s' command not found", cmd)

        if self.cfg.get('separate_build_dir', True):
            builddir = create_unused_dir(self.builddir, 'easybuild_obj')
            change_dir(builddir)

        # Make sure libdir doesn't get set to lib/x86_64-linux-gnu or something
        # on Debian/Ubuntu multiarch systems and others.
        no_Dlibdir = '-Dlibdir' not in self.cfg['configopts']
        no_libdir = '--libdir' not in self.cfg['configopts']
        if no_Dlibdir and no_libdir:
            self.cfg.update('configopts', '-Dlibdir=lib')

        cmd = "%(preconfigopts)s meson --prefix %(installdir)s %(configopts)s %(sourcedir)s" % {
            'configopts': self.cfg['configopts'],
            'installdir': self.installdir,
            'preconfigopts': self.cfg['preconfigopts'],
            'sourcedir': self.start_dir,
        }
        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        return out

    def build_step(self, verbose=False, path=None):
        """
        Build with Ninja.
        """
        parallel = ''
        if self.cfg['parallel']:
            parallel = "-j %s" % self.cfg['parallel']

        cmd = "%(prebuildopts)s ninja %(parallel)s %(buildopts)s" % {
            'buildopts': self.cfg['buildopts'],
            'parallel': parallel,
            'prebuildopts': self.cfg['prebuildopts'],
        }
        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        return out

    def test_step(self):
        """
        Run tests using Ninja.
        """
        if self.cfg['runtest']:
            cmd = "%s %s %s" % (self.cfg['pretestopts'], self.cfg['runtest'], self.cfg['testopts'])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)
            return out

    def install_step(self):
        """
        Install with 'ninja install'.
        """
        parallel = ''
        if self.cfg['parallel']:
            parallel = "-j %s" % self.cfg['parallel']

        cmd = "%(preinstallopts)s ninja %(parallel)s %(installopts)s install" % {
            'installopts': self.cfg['installopts'],
            'parallel': parallel,
            'preinstallopts': self.cfg['preinstallopts'],
        }
        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        return out
