##
# Copyright 2009-2019 Ghent University
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
EasyBuild support for building and installing Julia packages, implemented as an easyblock

@author: Victor Holanda (CSCS)
@author: Samuel Omlin (CSCS)
"""
import os
import shutil

import easybuild.tools.toolchain as toolchain

from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import mkdir
from easybuild.tools.run import run_cmd, parse_log_for_error


class JuliaPackage(ExtensionEasyBlock):
    """
    Install an Julia package as a separate module, or as an extension.
    """

    @staticmethod
    def extra_options(extra_vars=None):
        if extra_vars is None:
            extra_vars = {}

        extra_vars.update({
            'arch_name': [None, "Change julia's Project.toml pathname", CUSTOM],
            'mpiexec':  [None, "Set the mpiexec command", CUSTOM],
            'mpiexec_args':  [None, "Set the mpiexec command args", CUSTOM],
        })
        return ExtensionEasyBlock.extra_options(extra_vars=extra_vars)

    def __init__(self, *args, **kwargs):
        """Initliaze RPackage-specific class variables."""

        super(JuliaPackage, self).__init__(*args, **kwargs)
        self.package_name = self.name
        names = self.package_name.split('.')
        if len(names) > 1:
            self.package_name = ''.join(names[:-1])

        julia_env_name = os.getenv('EBJULIA_ENV_NAME', '')
        self.depot=os.path.join(self.installdir, 'extensions')
        self.projectdir=os.path.join(self.depot, 'environments', julia_env_name)
        self.log.info("Depot for package installations: %s" % self.depot)

    def patch_step(self, beginpath=None):
        pass

    def fetch_sources(self, sources=None, checksums=None):
        pass

    def extract_step(self):
        """Source should not be extracted."""
        pass

    def configure_step(self):
        """No configuration for installing Julia packages."""
        pass

    def build_step(self):
        """No separate build step for Julia packages."""
        pass

    def make_julia_cmd(self, remove=False):
        """Create a command to run in julia to install an julia package."""

        install_opts = ""
        if self.cfg['installopts']:
            install_opts = self.cfg['installopts']
        else:
            install_opts = "name=\"%s\", version=\"%s\"" % (self.package_name, self.version)

        pre_cmd = '%s unset EBJULIA_USER_DEPOT_PATH && export EBJULIA_ADMIN_DEPOT_PATH=%s && export JULIA_DEPOT_PATH=%s && export JULIA_PROJECT=%s' % (self.cfg['preinstallopts'], self.depot, self.depot, self.projectdir)

        has_mpi = False
        if self.toolchain.options.get('usempi', None):
            has_mpi = True

        if (self.cfg['mpiexec'] or self.cfg['mpiexec_args']) and not has_mpi:
            raise EasyBuildError("When enabling building with mpi, also enable the 'usempi' toolchain option.")

        if self.toolchain.toolchain_family() == toolchain.CRAYPE and has_mpi:
          cray_mpich_dir = os.getenv('CRAY_MPICH_DIR', '')
          pre_cmd += ' && export JULIA_MPI_BINARY=system'
          pre_cmd += ' && export JULIA_MPI_PATH="%s"' % cray_mpich_dir
          pre_cmd += ' && export JULIA_MPICC="cc"'

        if self.cfg['mpiexec']:
            pre_cmd += ' && export JULIA_MPIEXEC="%s"' % self.cfg['mpiexec']

        if self.cfg['mpiexec_args']:
            pre_cmd += ' && export JULIA_MPIEXEC_ARGS="%s"' % self.cfg['mpiexec_args']

        if self.cfg['arch_name'] == 'gpu':
            pre_cmd += ' && export JULIA_CUDA_USE_BINARYBUILDER=false'

        if remove:
            cmd = ' && '.join([pre_cmd, "julia --eval 'using Pkg; Pkg.rm(PackageSpec(%s))'" % install_opts])
        else:
            cmd = ' && '.join([pre_cmd, "julia --eval 'using Pkg; Pkg.add(PackageSpec(%s))'" % install_opts])

        return cmd

    def install_step(self):
        """Install procedure for Julia packages."""

        cmd = self.make_julia_cmd(remove=False)
        cmdttdouterr, _ = run_cmd(cmd, log_all=True, simple=False, regexp=False)

        cmderrors = parse_log_for_error(cmdttdouterr, regExp="^ERROR:")
        if cmderrors:
            cmd = self.make_julia_cmd(remove=True)
            run_cmd(cmd, log_all=False, log_ok=False, simple=False, inp=stdin, regexp=False)
            raise EasyBuildError("Errors detected during installation of Julia package %s!", self.name)
        else:
            self.log.info("Julia package %s installed succesfully" % self.name)

    def run(self):
        """Install Julia package as an extension."""
        self.install_step()

    def sanity_check_step(self, *args, **kwargs):
        """
        Custom sanity check for Julia packages
        """
        #NOTE: we don't use Pkg.status with arguments as only supported for Julia >=v1.1
        cmd = "unset EBJULIA_USER_DEPOT_PATH && export EBJULIA_ADMIN_DEPOT_PATH=%s && export JULIA_DEPOT_PATH=%s && export JULIA_PROJECT=%s && julia --eval 'using Pkg; Pkg.status()'" % (self.depot, self.depot, self.projectdir)
        cmdttdouterr, _ = run_cmd(cmd, log_all=True, simple=False, regexp=False)
        self.log.error("Julia package %s sanity returned %s" % (self.name, cmdttdouterr))
        return len(parse_log_for_error(cmdttdouterr, regExp="%s\s+v%s" % (self.package_name, self.version))) != 0

