##
# Copyright 2012-2021 Ghent University
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
EasyBlock for installing jaxlib, implemented as an easyblock

@author: Denis Kristak (INUITS)
"""

from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_version


class EB_jaxlib(PythonPackage):
    """Support for installing jaxlib. Extension of the existing PythonPackage easyblock 
    """
    def build_step(self):
        """Custom build procedure for jaxlib."""
        # Compose command to run build.py script with all necessary options
        cmd = [
            self.cfg['prebuildopts'],
            self.python_cmd,
            'build/build.py ',
            '--target_cpu_features=native ',
            '--bazel_startup_options="--output_user_root=%s" ' % self.builddir,
            '--bazel_path="$EBROOTBAZEL/bin/bazel" ',
            '--bazel_options=--subcommands ',
            '--bazel_options=--jobs=%s' % self.cfg['parallel'],
            '--bazel_options=--action_env=PYTHONPATH ',
            '--bazel_options=--action_env=EBPYTHONPREFIXES',
            self.cfg['buildopts']
        ]

        run_cmd(' '.join(cmd), log_all=True, simple=True, log_ok=True)

    def install_step(self):
        """We make `use_pip = True` a rule"""
        cmd = [
            'pip',
            'install',
            '--prefix=%s' % self.installdir,
            'dist/*.whl'
        ]
        run_cmd(' '.join(cmd), log_all=True, log_ok=True)

    # can't run tests in sanity check step, because build dependencies must be available
    # also not in test step in EC, since it doesnt exist in `Bundle` easyblocks
    def post_install_step(self):
        """Testing installation"""
        pyshortver = '.'.join(get_software_version('Python').split('.')[:2])
        cmd = [
            "cd %%(builddir)s/jax-jaxlib-v%s && " % self.version,
            "PYTHONPATH=%s/lib/python%s/site-packages:$PYTHONPATH " % (self.installdir, pyshortver),
            "pytest -n auto tests",
        ]
        run_cmd(cmd, log_all=True, log_ok=True)

        super(EB_jaxlib, self).build_step()
