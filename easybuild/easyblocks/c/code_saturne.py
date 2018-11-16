##
# Copyright 2009-2018 Ghent University
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
EasyBuild support for building and installing Code_Saturne, implemented as an easyblock

@author: Metin Cakircali (Juelich Supercomputing Centre)
"""

import os

import easybuild.tools.environment as env
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import apply_regex_substitutions
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Code_underscore_Saturne(EasyBlock):
    """Support for building and installing Code_Saturne."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Code_Saturne."""
        extra_vars = EasyBlock.extra_options(extra_vars)

        # add more custom easyconfig parameters specific to OpenFOAM
        extra_vars.update({
            'debug': [False, "Build the debug version.", CUSTOM],
            'slurm': [False, "Build for the slurm resource manager.", CUSTOM],
        })

        return extra_vars

    def prepare_step(self, *args, **kwargs):
        """Prepare step for Code_Saturne obtained from the repository."""
        super(EB_Code_underscore_Saturne, self).prepare_step(*args, **kwargs)

        self.log.info("Running ./sbin/bootstrap ...")

        cmd = './sbin/bootstrap'
        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=True)

        return out

    def configure_step(self):
        """Configure step for Code_Saturne."""

        self.log.info("Configuration step is running...")

        # only use the opt flags
        env.setvar("CFLAGS", os.environ['OPTFLAGS'])
        env.setvar("CXXFLAGS", os.environ['OPTFLAGS'])
        env.setvar("FCFLAGS", os.environ['OPTFLAGS'])

        cmd = ' '.join([
            './configure',
            '--prefix=' + self.installdir,
            '--without-modules',
            self.cfg['configopts'],
            ])

        if self.cfg['debug']:
            cmd = ' '.join([cmd, '--enable-debug'])

        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=True)

        return out

    def build_step(self):
        """ Build step for Code_Saturne."""

        paracmd = ''
        if self.cfg['parallel']:
            paracmd = "-j %s" % self.cfg['parallel']

        cmd = "make %s" % paracmd

        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=True)

        return out

    def install_step(self):
        """ Build step for Code_Saturne."""

        cmd = "make install"

        (out, _) = run_cmd(cmd, log_all=True, simple=False, log_output=True)

        return out

    def post_install_step(self):
        """Custom post install step for Code_Saturne."""
        super(EB_Code_underscore_Saturne, self).post_install_step()

        # create a "etc/code_saturne.cfg" and modify it to match SLURM
        if self.cfg['slurm']:

            self.log.info("Running the post-install SLURM step ...")

            target_path = os.path.join(self.installdir, 'etc/code_saturne.cfg')
            from_path = target_path + '.template'

            apply_regex_substitutions(from_path,
                                      [(r"# batch =", r"batch = SLURM")])
            apply_regex_substitutions(from_path,
                                      [(r"# mpiexec = mpiexec", r"mpiexec = srun")])
            apply_regex_substitutions(from_path,
                                      [(r"# mpiexec_n = ' -n '", r"mpiexec_n = ' -n '")])
            apply_regex_substitutions(from_path,
                                      [(r"# mpiexec_n_per_node =", r"mpiexec_n_per_node = ' --ntasks-per-node '")])

            os.rename(from_path, target_path)

    def sanity_check_step(self):
        """Custom sanity check step for Code_Saturne."""

        shlib_ext = get_shared_lib_ext()

        custom_paths = {
            'files': ['bin/code_saturne', 'lib/libsaturne.%s' % shlib_ext],
            'dirs': ['bin', 'lib', 'libexec', 'include', 'etc'],
        }

        super(EB_Code_underscore_Saturne, self).sanity_check_step(
            custom_paths=custom_paths)

    def make_module_extra(self, altroot=None, altversion=None):
        """Extra environment variables for Code_Saturne."""

        txt = super(EB_Code_underscore_Saturne, self).make_module_extra()

        cs_bashPath = os.path.join(self.installdir, 'etc', 'bash_completion.d', 'code_saturne')
        txt += self.module_generator.set_environment('CS_BASH', cs_bashPath)

        return txt
