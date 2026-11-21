##
# Copyright 2009-2023 Ghent University
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
EasyBuild support for building and installing FSL 6.0.7+, implemented as an easyblock

@author: Duncan Mortimer (University of Oxford)
"""

import os

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.conda import Conda
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.module_generator import ModuleGeneratorTcl, ModuleGeneratorLua


class EB_FSLCONDA(Conda):
    """Support for building and installing FSL via 'conda'."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Conda easyblock."""
        extra_vars = Conda.extra_options(extra_vars)
        extra_vars.update({
            'create_wrappers': [
                True,
                "Whether to create share/fsl/bin and use this instead of FSLDIR/bin." +
                "This avoids poluting the path with internal versions of libraries",
                CUSTOM],
        })
        return extra_vars

    def install_step(self):
        """Set FSL_CREATE_WRAPPER_SCRIPTS and then call install_step from Conda."""

        if self.cfg['create_wrappers']:
            env.setvar('FSL_CREATE_WRAPPER_SCRIPTS', '1')

        # Tell mamba not to abort if the download is taking time
        # https://github.com/mamba-org/mamba/issues/1941
        env.setvar('MAMBA_NO_LOW_SPEED_LIMIT', '1')

        env.setvar('FSLDIR', self.installdir)
        super(EB_FSLCONDA, self).install_step()

    def make_module_req_guess(self):
        """Set correct PATH and LD_LIBRARY_PATH variables."""

        if self.cfg['create_wrappers']:
            guesses = {
                'PATH': ['share/fsl/bin', ],
            }
        else:
            guesses = {
                'PATH': ['bin', ],
            }

        return guesses

    def make_module_extra(self):
        """Add setting of FSLDIR in module."""

        txt = super(EB_FSLCONDA, self).make_module_extra()
        fsldir = "$root"
        txt += self.module_generator.set_environment("FSLDIR", fsldir)
        txt += self.module_generator.set_environment("FSLCONFDIR", os.path.join(fsldir, 'config'))
        if self.cfg['create_wrappers']:
            fsldir_bin = os.path.join(fsldir, 'share', 'fsl', 'bin')
        else:
            fsldir_bin = os.path.join(fsldir, 'bin')
        txt += self.module_generator.set_environment("FSLTCLSH", os.path.join(fsldir_bin, 'fsltclsh'))
        txt += self.module_generator.set_environment("FSLWISH", os.path.join(fsldir_bin, 'fslwish'))

        for env_var in [
                ('FSLOUTPUTTYPE', 'NIFTI_GZ', ),
                ('FSLMULTIFILEQUIT', 'TRUE', ),
                ('FSL_LOAD_NIFTI_EXTENSIONS', '0', ),
                ('FSL_SKIP_GLOBAL', '0', ),
                ]:

            if isinstance(self.module_generator, ModuleGeneratorTcl):
                txt += self.module_generator.conditional_statement(
                    'info exists %s' % env_var[0],
                    'setenv "%s" "%s"' % env_var,
                    negative=True)
            elif isinstance(self.module_generator, ModuleGeneratorLua):
                txt += self.module_generator.conditional_statement(
                    'os.getenv("%s") == nil' % env_var[0],
                    'setenv("%s", "%s")' % env_var,
                    negative=True)
        return txt

    def sanity_check_step(self):
        """Custom sanity check for FSL"""

        custom_paths = {
            'files': ['LICENCE.FSL', ],
            'dirs': [
                'bin', 'config', 'data', 'doc',
                'etc', 'include', 'lib', 'python',
                'share', 'src', 'tcl',
                ],
        }
        if self.cfg['create_wrappers']:
            custom_paths['dirs'].append('share/fsl/bin')
        super(EB_FSLCONDA, self).sanity_check_step(custom_paths=custom_paths)
