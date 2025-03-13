##
# Copyright 2009-2025 Ghent University
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
EasyBuild support for installing software using 'conda', implemented as an easyblock.

@author: Jillian Rowe (New York University Abu Dhabi)
@author: Kenneth Hoste (HPC-UGent)
"""
from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root
from easybuild.tools.build_log import EasyBuildError


class Conda(Binary):
    """Support for installing software using 'conda'."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to Conda easyblock."""
        extra_vars = Binary.extra_options(extra_vars)
        extra_vars.update({
            'channels': [None, "List of conda channels to pass to 'conda install'", CUSTOM],
            'environment_file': [None, "Conda environment.yml file to use with 'conda env create'", CUSTOM],
            'remote_environment': [None, "Remote conda environment to use with 'conda env create'", CUSTOM],
            'requirements': [None, "Requirements specification to pass to 'conda install'", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize class variables."""
        super().__init__(*args, **kwargs)

        # Do not add installation to search paths for headers or libraries to avoid
        # that the conda environment is used by other software at building or linking time.
        # LD_LIBRARY_PATH issue discusses here:
        # http://superuser.com/questions/980250/environment-module-cannot-initialize-tcl
        mod_env_headers = self.module_load_environment.alias_vars(MODULE_LOAD_ENV_HEADERS)
        mod_env_libs = ['LD_LIBRARY_PATH', 'LIBRARY_PATH']
        mod_env_cmake = ['CMAKE_LIBRARY_PATH', 'CMAKE_PREFIX_PATH']
        for disallowed_var in mod_env_headers + mod_env_libs + mod_env_cmake:
            self.module_load_environment.remove(disallowed_var)
            self.log.debug(f"Purposely not updating ${disallowed_var} in {self.name} module file")

    def extract_step(self):
        """Copy sources via extract_step of parent, if any are specified."""
        if self.src:
            super(Conda, self).extract_step()

    def install_step(self):
        """Install software using 'conda env create' or 'conda create' & 'conda install'
        (or the 'mamba', etc., equivalent)."""
        if (get_software_root('anaconda2') or get_software_root('miniconda2') or
                get_software_root('anaconda3') or get_software_root('miniconda3') or
                get_software_root('miniforge3')):
            conda_cmd = 'conda'
        elif get_software_root('mamba'):
            conda_cmd = 'mamba'
        elif get_software_root('micromamba'):
            conda_cmd = 'micromamba'
        else:
            raise EasyBuildError("No conda/mamba/micromamba available.")

        # initialize conda environment
        # setuptools is just a choice, but *something* needs to be there
        cmd = f"{conda_cmd} config --add create_default_packages setuptools"
        run_shell_cmd(cmd)

        if self.cfg['environment_file'] or self.cfg['remote_environment']:

            if self.cfg['environment_file']:
                env_spec = '-f ' + self.cfg['environment_file']
            else:
                env_spec = self.cfg['remote_environment']

            # use --force to ignore existing installation directory
            cmd = f"{self.cfg['preinstallopts']} {conda_cmd} env create "
            cmd += f"--force {env_spec} -p {self.installdir}"
            run_shell_cmd(cmd)

        else:

            if self.cfg['requirements']:

                install_args = f"-y {self.cfg['requirements']} "
                if self.cfg['channels']:
                    install_args += ' '.join('-c ' + chan for chan in self.cfg['channels'])

                self.log.info("Installed conda requirements")

            cmd = f"{self.cfg['preinstallopts']} {conda_cmd} create "
            cmd += f"--force -y -p {self.installdir} {install_args}"
            run_shell_cmd(cmd)

        # clean up
        cmd = f"{conda_cmd} clean -ya"
        run_shell_cmd(cmd)

    def make_module_extra(self):
        """Add the install directory to the PATH."""
        txt = super(Conda, self).make_module_extra()
        txt += self.module_generator.set_environment('CONDA_ENV', self.installdir)
        txt += self.module_generator.set_environment('CONDA_PREFIX', self.installdir)
        txt += self.module_generator.set_environment('CONDA_DEFAULT_ENV', self.installdir)
        self.log.debug("make_module_extra added this: %s", txt)
        return txt
