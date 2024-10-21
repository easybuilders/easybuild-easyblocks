##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing MSM, implemented as an easyblock
@author: Davide Vanzo (Vanderbilt University)
"""
import os

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.makecp import MakeCp
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir, change_dir, mkdir, remove_dir
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root
from easybuild.framework.easyconfig import CUSTOM


class EB_MSM(MakeCp):
    """Support for building and installing MSM."""
    @staticmethod
    def extra_options(extra_vars=None):
        """Change default values of options"""
        extra = MakeCp.extra_options()
        # files_to_copy is not mandatory here
        extra['files_to_copy'][2] = CUSTOM
        return extra

    def __init__(self, *args, **kwargs):
        """Initialize MSM specific variables."""
        super(EB_MSM, self).__init__(*args, **kwargs)
        self.sources_root = os.path.join(self.builddir, 'MSM_HOCR-%s' % self.version)
        self.binfiles = [
            'estimate_metric_distortion', 'msm', 'msmapplywarp',
            'msm_metric_sim', 'msmresample', 'surfconvert'
        ]

    def configure_step(self):
        """Create directories, copy required files and set env vars."""

        # Ensure that nothing has been left over from previous installation attempts.
        # This is necessary here since directories must be created before building
        # and not removed before the installation step.
        remove_dir(self.installdir)
        mkdir(self.installdir)

        # Create directories recursively
        dirpath = self.installdir
        for dirname in ['extras', 'include']:
            dirpath = os.path.join(dirpath, dirname)
            mkdir(dirpath)
            self.log.debug("Created directory: %s" % dirpath)

        source_dir = os.path.join(self.sources_root, 'extras', 'ELC1.04', 'ELC')
        dest_dir = os.path.join(self.installdir, 'extras', 'include', 'ELC')
        copy_dir(source_dir, dest_dir)

        # FSL is a required dependency since it provides FastPDlib
        fsl_root = get_software_root('FSL')
        if not fsl_root:
            raise EasyBuildError("Required FSL dependency not found")

        # Find the machine type identified by FSL
        cmd = ". %s/fsl/etc/fslconf/fslmachtype.sh" % fsl_root
        (out, _) = run_cmd(cmd, log_all=True, simple=False)
        fslmachtype = out.strip()
        self.log.debug("FSL machine type: %s" % fslmachtype)

        env.setvar('FSLDEVDIR', self.installdir)
        env.setvar('FSLCONFDIR', os.path.join(fsl_root, 'fsl', 'config'))
        env.setvar('FSLMACHTYPE', fslmachtype)

    def build_step(self):
        """Build MSM one component at a time."""

        components = ['newmesh', 'DiscreteOpt', 'MSMRegLib', 'MSM']

        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        cmd = ' '.join(['make', paracmd, 'install'])

        for comp in components:
            target_dir = os.path.join(self.sources_root, 'src', comp)
            self.log.debug("Building %s in directory %s", comp, target_dir)
            change_dir(target_dir)
            run_cmd(cmd, log_all=True, simple=True, log_output=True)

    def make_installdir(self):
        """Override installdir creation"""

        self.log.warning("Not removing installation directory %s" % self.installdir)
        self.cfg['keeppreviousinstall'] = True
        super(EB_MSM, self).make_installdir()

    def install_step(self):
        """Define files to be copied at installation."""

        self.cfg['files_to_copy'] = [([os.path.join('src', 'MSM', f) for f in self.binfiles], 'bin')]
        super(EB_MSM, self).install_step()

    def sanity_check_step(self):
        """Custom sanity check for MSM."""

        custom_paths = {
            'files': [os.path.join('bin', f) for f in self.binfiles],
            'dirs': ['doc', 'include', 'lib']
        }
        super(EB_MSM, self).sanity_check_step(custom_paths=custom_paths)
