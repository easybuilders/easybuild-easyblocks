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

eOn exposes each optional potential and solver as a Meson option, and the set
of options changes between releases. This easyblock turns on every option whose
dependencies are present, and passes only options the unpacked source declares,
so an easyconfig builds as much of eOn as its dependency list allows. Feature
options get enabled/disabled, deprecated options are left unset, and Meson does
not download wraps.

@author: Rohit Goswami (SURF)
"""
import os
import re

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.environment import setvar
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, get_cpu_architecture

# Meson option -> EasyBuild names of the dependencies it needs (client/meson.build)
OPTION_DEPS = {
    'with_serve': ['rgpot', 'CapnProto'],
    'with_xtb': ['xtb'],
    'with_ase': ['pybind11', 'ASE'],
    'with_pyeonclient': ['nanobind'],
    'with_metatomic': ['PyTorch', 'metatomic-torch'],
}

OPTION_START_RE = re.compile(r"^\s*option\(\s*'(\w+)'", re.M)
OPTION_TYPE_RE = re.compile(r"\btype\s*:\s*'(\w+)'")
OPTION_DEPRECATED_RE = re.compile(r"\bdeprecated\s*:\s*(true|'|\[|\{)")


def parse_meson_options(text):
    """
    Map each option a meson.options or meson_options.txt declares to (type, deprecated).

    eOn turns options into features and deprecates others between releases
    (with_mpi became a feature in 3.5.0, with_rgpot is deprecated since 3.4.0).
    """
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    starts = list(OPTION_START_RE.finditer(text))
    options = {}
    for idx, match in enumerate(starts):
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
        body = text[match.end():end]
        opt_type = OPTION_TYPE_RE.search(body)
        options[match.group(1)] = (opt_type.group(1) if opt_type else None, bool(OPTION_DEPRECATED_RE.search(body)))
    return options


# search paths that Meson's dependency('hwy') reads (pkg-config, then CMake)
HWY_SEARCH_VARS = ('PKG_CONFIG_PATH', 'CMAKE_PREFIX_PATH')


def drop_prefix(path_value, prefix):
    """Remove the entries of a colon-separated search path that sit under prefix."""
    prefix = os.path.normpath(prefix)
    kept = [p for p in path_value.split(os.pathsep)
            if p and os.path.normpath(p) != prefix and not os.path.normpath(p).startswith(prefix + os.sep)]
    return os.pathsep.join(kept)


def meson_value(opt_type, value):
    """Spell a boolean the way Meson accepts it for an option of this type."""
    if opt_type == 'feature':
        return 'enabled' if value else 'disabled'
    return str(value).lower()


class EB_eOn(MesonNinja):
    """Support for building and installing eOn."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Custom easyconfig parameters for eOn."""
        extra_vars = MesonNinja.extra_options(extra_vars)
        extra_vars.update({
            'highway_on_aarch64': [False, "Let eOn use the Highway dependency on aarch64 (off by default: "
                                          "Highway is optional in eOn, and its SVE targets fail on aarch64/generic)",
                                   CUSTOM],
        })
        return extra_vars

    def _hide_highway(self):
        """
        Keep eOn from finding Highway on aarch64.

        eOn has no Meson option for Highway: client/meson.build looks it up with
        dependency('hwy', required: false), so it is used whenever pkg-config or
        CMake can see it. On aarch64 this drops the Highway prefix from those
        search paths; with --wrap-mode=nodownload the wrap fallback does not
        fetch anything, and eOn builds its scalar code paths.
        Returns the list of variables that changed.
        """
        hwy_root = get_software_root('Highway')
        if not hwy_root or get_cpu_architecture() != AARCH64 or self.cfg['highway_on_aarch64']:
            return []
        changed = []
        for var in HWY_SEARCH_VARS:
            old = os.environ.get(var, '')
            new = drop_prefix(old, hwy_root)
            if new != old:
                setvar(var, new)
                changed.append(var)
        self.log.info("eOn: aarch64, configuring without Highway (%s); removed it from %s",
                      hwy_root, ', '.join(changed) or 'no search path')
        return changed

    def _declared_options(self):
        """Type and deprecation state of each Meson option the source tree declares."""
        # MesonNinja passes build_dir to meson as the source directory
        src = self.cfg['build_dir'] or self.start_dir
        for fn in ('meson.options', 'meson_options.txt'):
            path = os.path.join(src, fn)
            if os.path.isfile(path):
                return parse_meson_options(read_file(path))
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
                continue
            opt_type, deprecated = declared[opt]
            if deprecated:
                self.log.info("eOn: Meson option %s is deprecated, not setting it", opt)
            elif '-D%s=' % opt in self.cfg['configopts']:
                self.log.info("eOn: %s is set in configopts, leaving it", opt)
            else:
                self.cfg.update('configopts', '-D%s=%s' % (opt, meson_value(opt_type, value)))
                if value:
                    enabled.append(opt)
        self.log.info("eOn: enabled Meson options: %s", ', '.join(enabled) or 'none')

        # with_metatomic links libtorch from the PyTorch installation, not from pip
        if 'with_metatomic' in enabled and 'torch_path' in declared and '-Dtorch_path=' not in self.cfg['configopts']:
            pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
            torch_path = os.path.join(get_software_root('PyTorch'), 'lib', 'python%s' % pyshortver,
                                      'site-packages', 'torch')
            if not os.path.isdir(torch_path):
                raise EasyBuildError("with_metatomic: no torch package at %s", torch_path)
            self.cfg.update('configopts', '-Dtorch_path=%s' % torch_path)

        self._hide_highway()

        # every dependency comes from the easyconfig; a missing one fails here
        # instead of Meson fetching a wrap from the network
        if 'wrap_mode' not in self.cfg['configopts'] and '--wrap-mode' not in self.cfg['configopts']:
            self.cfg.update('configopts', '--wrap-mode=nodownload')

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
