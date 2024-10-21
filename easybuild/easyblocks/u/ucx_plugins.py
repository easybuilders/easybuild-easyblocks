# -*- coding: utf-8 -*-
##
# Copyright 2012-2024 Ghent University
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
EasyBuild support for UCX plugins (modules), implemented as an easyblock

@author: Mikael Öhman (Chalmers University of Techonology)
"""
from collections import defaultdict
from itertools import chain
import os

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.modules import get_software_root
from easybuild.tools.py2vs3 import subprocess_popen_text
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_UCX_Plugins(ConfigureMake):
    """Support for building additional plugins for a existing UCX module"""

    def __init__(self, *args, **kwargs):
        """Custom initialization for UCX-Plugins."""
        super(EB_UCX_Plugins, self).__init__(*args, **kwargs)
        self._plugins = None
        self.makefile_dirs = []

    @property
    def plugins(self):
        """Property to determine list of plugins based on loaded dependencies, or return cached list of plugins."""
        if self._plugins is None:
            plugins = defaultdict(list)
            dep_names = self.cfg.dependency_names()

            if 'CUDAcore' in dep_names or 'CUDA' in dep_names:
                for key in ('ucm', 'uct', 'ucx_perftest'):
                    plugins[key].append('cuda')

                if 'GDRCopy' in dep_names:
                    plugins['uct_cuda'].append('gdrcopy')

            if 'ROCm' in dep_names:
                for key in ('ucm', 'uct', 'ucx_perftest'):
                    plugins[key].append('rocm')

            self._plugins = dict(plugins)
            self.log.info("Creating plugins for %s", ", ".join(sorted(set(chain(*plugins.values())))))
        return self._plugins

    def configure_step(self):
        """Customize configuration for building requested plugins."""
        # make sure that required dependencies are loaded
        if not get_software_root('UCX'):
            raise EasyBuildError("UCX is a required dependency")

        self.cfg.update('preconfigopts', 'autoreconf -i &&')

        configopts = '--enable-optimizations --without-java --disable-doxygen-doc '
        # omit the lib subdirectory since we are just installing plugins
        configopts += '--libdir=%(installdir)s '
        # include the configure options from contrib/configure-release
        configopts += '--disable-logging --disable-debug --disable-assertions --disable-params-check '

        cudaroot = get_software_root('CUDAcore') or get_software_root('CUDA')
        if cudaroot:
            configopts += '--with-cuda=%s ' % cudaroot

            gdrcopyroot = get_software_root('GDRCopy')
            if gdrcopyroot:
                configopts += '--with-gdrcopy=%s ' % gdrcopyroot

            self.makefile_dirs.extend(os.path.join(x, 'cuda') for x in ('uct', 'ucm', 'tools/perf'))

        rocmroot = get_software_root('ROCm')
        if rocmroot:
            configopts += '--with-rocm=%s ' % rocmroot
            self.makefile_dirs.extend(os.path.join(x, 'rocm') for x in ('uct', 'ucm', 'tools/perf'))

        self.cfg.update('configopts', configopts)

        super(EB_UCX_Plugins, self).configure_step()

    def build_step(self):
        """Build plugins"""
        for makefile_dir in self.makefile_dirs:
            run_cmd('make -C src/%s V=1' % makefile_dir)

    def install_step(self):
        """Install plugins"""
        for makefile_dir in self.makefile_dirs:
            run_cmd('make -C src/%s install' % (makefile_dir))

    def make_module_extra(self, *args, **kwargs):
        """Add extra statements to generated module file specific to UCX plugins"""
        txt = super(EB_UCX_Plugins, self).make_module_extra(*args, **kwargs)

        base_conf = dict()
        cmd = ['ucx_info', '-b']
        full_cmd = ' '.join(cmd)
        self.log.info("Running command '%s'" % full_cmd)
        proc = subprocess_popen_text(cmd, env=os.environ)
        (stdout, stderr) = proc.communicate()
        ec = proc.returncode
        msg = "Command '%s' returned with %s: stdout: %s; stderr: %s" % (full_cmd, ec, stdout, stderr)
        if ec:
            self.log.info(msg)
            raise EasyBuildError('Failed to determine base UCX info: %s', stderr)

        for line in stdout.split('\n'):
            try:
                variable, value = line.split(None, 3)[1:]
            except ValueError:
                continue
            if 'MODULES' in variable:
                base_conf[variable] = [x for x in value.strip('"').split(':') if x]

        txt += self.module_generator.prepend_paths('UCX_MODULE_DIR', 'ucx')
        for framework, extra_plugins in self.plugins.items():
            if extra_plugins:
                variable = framework + '_MODULES'
                all_plugins = base_conf[variable] + extra_plugins
                plugins_str = ':' + ':'.join(all_plugins)
                txt += self.module_generator.set_environment('EB_UCX_' + variable, plugins_str)
        return txt

    def sanity_check_step(self):
        """Custom sanity check for UCX plugins."""

        custom_commands = ['ucx_info -d']

        shlib_ext = get_shared_lib_ext()
        files = []
        for framework, names in self.plugins.items():
            files.extend(os.path.join('ucx', 'lib%s_%s.%s' % (framework, name, shlib_ext)) for name in names)

        custom_paths = {
            'files': files,
            'dirs': [],
        }

        super(EB_UCX_Plugins, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)
