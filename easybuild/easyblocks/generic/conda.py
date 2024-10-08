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
EasyBuild support for installing software using 'conda', implemented as an easyblock.

@author: Jillian Rowe (New York University Abu Dhabi)
@author: Kenneth Hoste (HPC-UGent)
"""

import os
import yaml


from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root
from easybuild.tools.build_log import EasyBuildError
import easybuild.tools.systemtools as st

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
            'use_conda_lock': [False, "Whether to use conda-lock for reproducibility", CUSTOM],
            'provided_lock_file_name': [None, "Provided lock file name", CUSTOM],
        })
        return extra_vars

    def extract_step(self):
        """Copy sources via extract_step of parent, if any are specified."""
        if self.src:
            super(Conda, self).extract_step()

    def install_step(self):
        """Install software using 'conda env create' or 'conda create' & 'conda install'
        (or the 'mamba', etc., equivalent)."""
        if (get_software_root('anaconda2') or get_software_root('miniconda2') or
                get_software_root('anaconda3') or get_software_root('miniconda3') or get_software_root('miniforge3')):
            conda_cmd = 'conda'
        elif get_software_root('mamba'):
            conda_cmd = 'mamba'
        elif get_software_root('micromamba'):
            conda_cmd = 'micromamba'
        else:
            raise EasyBuildError("No conda/mamba/micromamba available.")
        
        # initialize conda environment
        # setuptools is just a choice, but *something* needs to be there
        cmd = "%s config --add create_default_packages setuptools" % conda_cmd
        run_cmd(cmd, log_all=True, simple=True)

        def get_system_platform_name():
            system = st.get_system_info()['os_type'].lower()
            machine = st.get_system_info()['cpu_arch'].lower()

            platforms = {
                "linux": {
                    "x86_64": "linux-64",
                    "aarch64": "linux-aarch64",
                    "ppc64le": "linux-ppc64le",
                    "s390x": "linux-s390x"
                },
                "darwin": {
                    "x86_64": "osx-64",
                    "arm64": "osx-arm64"
                },
                "windows": {
                    "x86_64": "win-64",
                    "amd64": "win-64",
                    "arm64": "win-arm64",
                    "x86": "win-32"
                },
                "zos": {
                    "z": "zos-z"
                }
            }

            return platforms.get(system, {}).get(machine)
        
        def check_lock_file_type(lock_file):
            _, ext = os.path.splitext(lock_file)
            if ext == ".lock":
                return "single"
            elif ext in [".yml", ".yaml"]:
                return "multi"
            else:
                raise EasyBuildError("The provided file is not a lock file")

        def verify_lock_file_platform(lock_file, platform_name):

            file_type = check_lock_file_type(lock_file)

            if file_type == "multi":
            # for a multi-platform lock file like conda-lock.yml
                with open(lock_file, 'r') as f:
                    lock_data = yaml.safe_load(f)
                    return platform_name in lock_data.get('metadata', []).get('platforms',[])
            else:
            # for a single-platform rendered lock file like conda-linux64.lock
                with open(lock_file, 'r') as f:
                    for line in f:
                        if line.startswith("# platform:"):
                            return line.split(":", 1)[1].strip() == platform_name


        if self.cfg['use_conda_lock']:
            lock_file =  self.cfg['provided_lock_file_name']        
            platform_name = get_system_platform_name()

            # the default name for rendered lock_file is 'conda-<platform>.lock'
            platform_rendered_lock_file='conda-{}.lock'.format(platform_name)      

            if not lock_file:
                # install conda-lock
                cmd = "%s install conda-lock" % conda_cmd
                run_cmd(cmd, log_all=True, simple=True)

                # ship environment file in installation
                super(Binary, self).fetch_sources(sources=[self.cfg['environment_file']])
                self.extract_step()

                # generate lock file and render
                cmd = "conda-lock -f %s -p %s && conda-lock render -p %s" % (
                    self.cfg['environment_file'], platform_name, platform_name)
                run_cmd(cmd, log_all=True, simple=True)

            
            else:

                lock_file_type = check_lock_file_type(lock_file)

                # ship lock_file in installation
                super(Binary, self).fetch_sources(sources=[lock_file])
                self.extract_step()
                
                # verify that a lock file for the current platform has been provided
                if not verify_lock_file_platform(lock_file,platform_name):
                    raise EasyBuildError("The provided lock file does not match this platform")


                if lock_file_type == "multi":

                    # install conda-lock
                    cmd = "%s install conda-lock" % conda_cmd
                    run_cmd(cmd, log_all=True, simple=True)
                    
                    # render
                    cmd = "conda-lock render -p %s %s" % (platform_name, lock_file)
                    run_cmd(cmd, log_all=True, simple=True)
                else:

                    platform_rendered_lock_file=lock_file                


            # use lock_file to create environment
            cmd = "%s %s create --file %s -p %s -y" % (self.cfg['preinstallopts'],conda_cmd, platform_rendered_lock_file, self.installdir)
            run_cmd(cmd, log_all=True, simple=True)

        elif self.cfg['environment_file'] or self.cfg['remote_environment']:

            if self.cfg['environment_file']:
                env_spec = '-f ' + self.cfg['environment_file']
            else:
                env_spec = self.cfg['remote_environment']

            # use --force to ignore existing installation directory
            cmd = "%s %s env create --force %s -p %s" % (self.cfg['preinstallopts'], conda_cmd,
                                                         env_spec, self.installdir)
            run_cmd(cmd, log_all=True, simple=True)

        else:

            if self.cfg['requirements']:

                install_args = "-y %s " % self.cfg['requirements']
                if self.cfg['channels']:
                    install_args += ' '.join('-c ' + chan for chan in self.cfg['channels'])

                self.log.info("Installed conda requirements")

            cmd = "%s %s create --force -y -p %s %s" % (self.cfg['preinstallopts'], conda_cmd,
                                                        self.installdir, install_args)
            run_cmd(cmd, log_all=True, simple=True)

        # clean up
        cmd = "%s clean -ya" % conda_cmd
        run_cmd(cmd, log_all=True, simple=True)

    def make_module_extra(self):
        """Add the install directory to the PATH."""
        txt = super(Conda, self).make_module_extra()
        txt += self.module_generator.set_environment('CONDA_ENV', self.installdir)
        txt += self.module_generator.set_environment('CONDA_PREFIX', self.installdir)
        txt += self.module_generator.set_environment('CONDA_DEFAULT_ENV', self.installdir)
        self.log.debug("make_module_extra added this: %s", txt)
        return txt

    def make_module_req_guess(self):
        """
        A dictionary of possible directories to look for.
        """
        # LD_LIBRARY_PATH issue discusses here
        # http://superuser.com/questions/980250/environment-module-cannot-initialize-tcl
        return {
            'PATH': ['bin', 'sbin'],
            'MANPATH': ['man', os.path.join('share', 'man')],
            'PKG_CONFIG_PATH': [os.path.join(x, 'pkgconfig') for x in ['lib', 'lib32', 'lib64', 'share']],
        }
