##
# Copyright 2017-2024 Ghent University
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
EasyBuild support for building and installing tensorflow-compresssion, implemented as an easyblock

@author: Ake Sandgren (Umea University)
"""
import glob
import os

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools import LooseVersion
from easybuild.tools.modules import get_software_version
from easybuild.tools.run import run_cmd


class EB_tensorflow_minus_compression(PythonPackage):

    def setup_build_dirs(self):
        """Setup temporary build directories"""
        # This is either the builddir (for standalone builds) or the extension sub folder when TFC is an extension
        # Either way this folder only contains the folder with the sources and hence we can use fixed names
        # for the subfolders
        parent_dir = os.path.dirname(self.start_dir)
        # Path where Bazel will store its output, build artefacts etc.
        self.output_user_root_dir = os.path.join(parent_dir, 'bazel-root')
        # Folder where wrapper binaries can be placed, where required. TODO: Replace by --action_env cmds
        self.wrapper_dir = os.path.join(parent_dir, 'wrapper_bin')

    def configure_step(self):
        """Custom configuration procedure for TensorFlow-Compression."""

        self.setup_build_dirs()

        # Options passed to the target (build/test), e.g. --config arguments
        self.target_opts = []

    def build_step(self):
        """Custom build procedure for TensorFlow-Compression."""

        bazel_version = get_software_version('Bazel')

        # Options passed to the bazel command
        self.bazel_opts = [
            '--output_user_root=%s' % self.output_user_root_dir,
        ]

        # Environment variables and values needed for Bazel actions.
        action_env = {}
        # A value of None is interpreted as using the invoking environments value
        INHERIT = None  # For better readability

        if self.toolchain.options.get('debug', None):
            self.target_opts.append('--strip=never')
            self.target_opts.append('--compilation_mode=dbg')

        for flag in os.getenv('CFLAGS', '').split(' '):
            self.target_opts.append('--copt="%s"' % flag)

        # make Bazel print full command line + make it verbose on failures
        # https://docs.bazel.build/versions/master/user-manual.html#flag--subcommands
        # https://docs.bazel.build/versions/master/user-manual.html#flag--verbose_failures
        self.target_opts.extend(['--subcommands', '--verbose_failures'])

        self.target_opts.append('--jobs=%s' % self.cfg['parallel'])

        # include install location of Python packages in $PYTHONPATH,
        # and specify that value of $PYTHONPATH should be passed down into Bazel build environment,
        # this is required to make sure that Python packages included as extensions are found at build time,
        # see also https://github.com/tensorflow/tensorflow/issues/22395
        pythonpath = os.getenv('PYTHONPATH', '')
        env.setvar('PYTHONPATH', os.pathsep.join([os.path.join(self.installdir, self.pylibdir), pythonpath]))

        # Make TFC find our modules. LD_LIBRARY_PATH gets automatically added
        action_env['CPATH'] = INHERIT
        action_env['LIBRARY_PATH'] = INHERIT
        action_env['PYTHONPATH'] = INHERIT
        # Also export $EBPYTHONPREFIXES to handle the multi-deps python setup
        # See https://github.com/easybuilders/easybuild-easyblocks/pull/1664
        if 'EBPYTHONPREFIXES' in os.environ:
            action_env['EBPYTHONPREFIXES'] = INHERIT

        # Ignore user environment for Python
        action_env['PYTHONNOUSERSITE'] = '1'

        # Use the same configuration (i.e. environment) for compiling and using host tools
        # This means that our action_envs are (almost) always passed
        # Fully removed in Bazel 6.0 and limited effect after at least 3.7 (see --host_action_env)
        if LooseVersion(bazel_version) < LooseVersion('6.0.0'):
            self.target_opts.append('--distinct_host_configuration=false')

        for key, value in sorted(action_env.items()):
            option = key
            if value is not None:
                option += "='%s'" % value

            self.target_opts.append('--action_env=' + option)
            if bazel_version >= '3.7.0':
                # Since Bazel 3.7 action_env only applies to the "target" environment, not the "host" environment
                # As we are not cross-compiling we need both be the same -> Duplicate the setting to host_action_env
                # See https://github.com/bazelbuild/bazel/commit/a463d9095386b22c121d20957222dbb44caef7d4
                self.target_opts.append('--host_action_env=' + option)

        # Compose final command
        cmd = (
            [self.cfg['prebuildopts']]
            + ['bazel']
            + self.bazel_opts
            + ['build']
            + self.target_opts
            + [self.cfg['buildopts']]
            # specify target of the build command as last argument
            + [':build_pip_pkg']
        )

        run_cmd(' '.join(cmd), log_all=True, simple=True, log_ok=True)

        # run generated 'build_pip_pkg' script to build the .whl
        cmd = (
            'python',
            'build_pip_pkg.py',
            'bazel-bin/build_pip_pkg.runfiles/tensorflow_compression',
            self.builddir,
            self.version
        )
        run_cmd(' '.join(cmd), log_all=True, simple=True, log_ok=True)

    def install_step(self):
        """Custom install procedure for TensorFlow-Compression."""

        whl_paths = glob.glob(os.path.join(self.builddir, 'tensorflow_compression-%s-*.whl' % self.version))
        if not whl_paths:
            whl_paths = glob.glob(os.path.join(self.builddir, 'tensorflow_compression-*.whl'))
        if len(whl_paths) == 1:
            self.cfg['install_src'] = whl_paths[0]

        super(EB_tensorflow_minus_compression, self).install_step()
