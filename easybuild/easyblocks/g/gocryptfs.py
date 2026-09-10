##
# Copyright 2009-2026 Ghent University
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
EasyBuild support for gocryptfs

@author: Georgios Kafanas (University of Luxembourg)
"""

from easybuild.easyblocks.generic.bundle import Bundle
from easybuild.framework.easyconfig import EasyConfig
from easybuild.tools.build_log import EasyBuildError
from datetime import datetime


def _set_gocryptfs_components(ec: EasyConfig):
    sources = ec['sources']
    if not sources:
        # Components should not be setup when no sources are not dfined
        # e.g. when used with `--modules-only`
        return

    if ec.get('components', None) or ec.get('default_component_specs', None):
        raise EasyBuildError("The '%s' easyblock does not accept a predefined 'components' entry'." % ec.name)

    ec['default_easyblock'] = 'ConfigureMake'
    ec['components'] = [
        (ec.name, ec.version, {
            'easyblock': 'GoPackage',
            'sources': sources,
            'start_dir': '%s_v%s_src-deps' % (ec.name, ec.version),
            'installopts': '-trimpath'
        }),
        ('%s-xray' % ec.name, ec.version, {
            'easyblock': 'GoPackage',
            'sources': sources,
            'start_dir': '%s_v%s_src-deps/gocryptfs-xray' % (ec.name, ec.version),
            'skipsteps':  ['build'],
            'modulename': '%s' % ec.name,
            'installopts': '-trimpath'
        }),
        ('%s-doc' % ec.name, ec.version, {
            'sources': sources,
            'start_dir': '%s_v%s_src-deps/Documentation' % (ec.name, ec.version),
            'skipsteps': ['configure'],
            'build_cmd': './MANPAGE-render.bash',
            'maxparallel': 1,
            'install_cmd': (
                'install -D --mode=u=rw,g=r,o=r'
                '    --target-directory="%(installdir)s/share/man/man1/" gocryptfs.1'
                ' && '
                'install -D --mode=u=rw,g=r,o=r'
                '    --target-directory="%(installdir)s/share/man/man1/" gocryptfs-xray.1'
            ),
        }),
        ('%s-license' % ec.name, ec.version, {
            'sources': sources,
            'start_dir': '%s_v%s_src-deps' % (ec.name, ec.version),
            'skipsteps': ['configure', 'build'],
            'install_cmd': (
                'install -D --mode=u=rw,g=r,o=r'
                '    --target-directory="%(installdir)s/share/licenses/gocryptfs" LICENSE'
            )
        }),
    ]


class EB_gocryptfs(Bundle):
    """Builds and installs a gocryptfs, and provides a dedicated module file."""
    def __init__(self, *args, **kwargs):
        self.sanity_check_all_components = True
        self.check_for_sources = False

        ec: EasyConfig = args[0]
        _set_gocryptfs_components(ec)

        super().__init__(*args, **kwargs)

        self.cfg['sanity_check_paths'] = {
            'files': ['bin/%(name)s', 'bin/%(name)s-xray'],
            'dirs': ['share'],
        }

        self.cfg['sanity_check_commands'] = [
            '%(name)s --help',
            '%(name)s-xray --help',
            '%(name)s --version | grep --quiet %(version)s',
            '%(name)s-xray --version | grep --quiet %(version)s',
        ]

    def _set_version_info(self, cfg: EasyConfig):
        installopts = cfg['installopts']

        version = r'-X \"main.GitVersion='
        version += str(self.version)
        version += r'\"'

        now = datetime.now()
        date = r'-X \"main.BuildDate='
        date += now.strftime('%Y-%m-%dT%H:%M:%S')
        date += r'\"'

        installopts += r' -ldflags="'
        installopts += version
        installopts += ' '
        installopts += date
        installopts += r'"'

        cfg['installopts'] = installopts

    def install_step(self):
        comp_instances = []
        for (cfg, comp) in self.comp_instances:
            name = cfg.name
            if name in {'gocryptfs', 'gocryptfs-xray'}:
                self._set_version_info(cfg)
            comp_instances.append((cfg, comp))
        self.comp_instances = comp_instances
        super().install_step()
