##
# Copyright 2026 Ghent University
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
EasyBuild support for building and installing eOn, implemented as an easyblock

eOn exposes each optional potential and solver as a Meson boolean, and the set
of options changes between releases. This easyblock turns on every option whose
dependencies are present, and passes only options the unpacked source declares,
so an easyconfig builds as much of eOn as its dependency list allows.

@author: Rohit Goswami (SURF)
"""
import os
import re

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd

# Meson option -> EasyBuild names of the dependencies it needs (client/meson.build)
OPTION_DEPS = {
    'with_rgpot': ['rgpot'],
    'with_serve': ['rgpot', 'CapnProto'],
    'with_xtb': ['xtb'],
    'with_parallel_neb': ['tbb'],
    'with_ase': ['pybind11', 'ASE'],
}

OPTION_RE = re.compile(r"^\s*option\(\s*'(\w+)'", re.M)


class EB_eOn(MesonNinja):
    """Support for building and installing eOn."""

    def _declared_options(self):
        """Names of the Meson options the source tree declares."""
        src = self.cfg['build_dir'] or self.start_dir
        for fn in ('meson.options', 'meson_options.txt'):
            path = os.path.join(src, fn)
            if os.path.isfile(path):
                return set(OPTION_RE.findall(read_file(path)))
        raise EasyBuildError("No meson.options or meson_options.txt found in %s", src)

    def _feature_options(self):
        """Value of each option this easyblock sets, before filtering on what the source declares."""
        opts = {
            'with_mpi': bool(self.toolchain.options.get('usempi', False)),
            'with_tests': bool(self.cfg['runtest']),
        }
        for opt, deps in OPTION_DEPS.items():
            opts[opt] = all(get_software_root(dep) for dep in deps)
        return opts

    def configure_step(self, *args, **kwargs):
        """Enable the eOn features the dependencies provide, then configure with Meson."""
        declared = self._declared_options()
        enabled = []
        for opt, value in sorted(self._feature_options().items()):
            if opt not in declared:
                self.log.info("eOn: source does not declare Meson option %s, not setting it", opt)
            elif '-D%s=' % opt in self.cfg['configopts']:
                self.log.info("eOn: %s is set in configopts, leaving it", opt)
            else:
                self.cfg.update('configopts', '-D%s=%s' % (opt, str(value).lower()))
                if value:
                    enabled.append(opt)
        self.log.info("eOn: enabled Meson options: %s", ', '.join(enabled) or 'none')
        return super().configure_step(*args, **kwargs)

    def test_step(self):
        """Run eOn's own test suite with meson test."""
        if self.cfg['runtest'] is True:
            cmd = ' '.join([
                self.cfg['pretestopts'],
                'meson test --suite eon --print-errorlogs',
                '--num-processes %s' % self.cfg.parallel,
                self.cfg['testopts'],
            ])
            return run_shell_cmd(cmd).output
        return super().test_step()

    def sanity_check_step(self):
        """Check eonclient, and the Python package when a Python dependency installs it."""
        custom_paths = {
            'files': ['bin/eonclient'],
            'dirs': [],
        }
        custom_commands = ['eonclient --version']
        if get_software_root('Python'):
            custom_paths['dirs'].append('lib/python%(pyshortver)s/site-packages/eon')
            custom_commands.append('python -c "import eon"')
        return super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
