##
# Copyright 2015-2024 Bart Oldeman
# Copyright 2016-2024 Forschungszentrum Juelich
#
# This file is triple-licensed under GPLv2 (see below), MIT, and
# BSD three-clause licenses.
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
EasyBuild support for installing NVIDIA HPC SDK compilers, based on the easyblock for PGI compilers

@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
@author: Damian Alvarez (Forschungszentrum Juelich)
@author: Andreas Herten (Forschungszentrum Juelich)
"""
import os
import fileinput
import re
import stat
import sys
import tempfile
import platform

from easybuild.tools import LooseVersion
from easybuild.easyblocks.generic.packedbinary import PackedBinary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import adjust_permissions, write_file
from easybuild.tools.run import run_cmd
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.config import build_option
from easybuild.tools.build_log import EasyBuildError, print_warning


# contents for siterc file to make PGI/NVHPC pick up $LIBRARY_PATH
# cfr. https://www.pgroup.com/support/link.htm#lib_path_ldflags
SITERC_LIBRARY_PATH = """
# get the value of the environment variable LIBRARY_PATH
variable LIBRARY_PATH is environment(LIBRARY_PATH);

# split this value at colons, separate by -L, prepend 1st one by -L
variable library_path is
default($if($LIBRARY_PATH,-L$replace($LIBRARY_PATH,":", -L)));

# add the -L arguments to the link line
append LDLIBARGS=$library_path;

# also include the location where libm & co live on Debian-based systems
# cfr. https://github.com/easybuilders/easybuild-easyblocks/pull/919
append LDLIBARGS=-L/usr/lib/x86_64-linux-gnu;
"""

# contents for minimal example compiled in sanity check, used to catch issue
# seen in: https://github.com/easybuilders/easybuild-easyblocks/pull/3240
NVHPC_MINIMAL_EXAMPLE = """
#include <ranges>

int main(){ return 0; }
"""


class EB_NVHPC(PackedBinary):
    """
    Support for installing the NVIDIA HPC SDK (NVHPC) compilers
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'default_cuda_version':      [None, "CUDA Version to be used as default (10.2 or 11.0 or ...)", CUSTOM],
            'module_add_cuda':           [False, "Add NVHPC's CUDA to module", CUSTOM],
            'module_add_math_libs':      [False, "Add NVHPC's math libraries to module", CUSTOM],
            'module_add_nccl':           [False, "Add NVHPC's NCCL library to module", CUSTOM],
            'module_add_nvshmem':        [False, "Add NVHPC's NVSHMEM library to module", CUSTOM],
            'module_add_profilers':      [False, "Add NVHPC's NVIDIA Profilers to module", CUSTOM],
            'module_byo_compilers':      [False, "BYO Compilers: Remove compilers from module", CUSTOM],
            'module_nvhpc_own_mpi':      [False, "Add NVHPC's packaged OpenMPI to module", CUSTOM]
        }
        return PackedBinary.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Easyblock constructor, define custom class variables specific to NVHPC."""
        super(EB_NVHPC, self).__init__(*args, **kwargs)

        # Ideally we should be using something like `easybuild.tools.systemtools.get_cpu_architecture` here, however,
        # on `ppc64le` systems this function returns `POWER` instead of `ppc64le`. Since this path needs to reflect
        # `arch` (https://easybuild.readthedocs.io/en/latest/version-specific/easyconfig_templates.html) the same
        # procedure from `templates.py` was reused here:
        architecture = 'Linux_%s' % platform.uname()[4]
        self.nvhpc_install_subdir = os.path.join(architecture, self.version)

    def install_step(self):
        """Install by running install command."""

        # EULA for NVHPC must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(more_info='https://docs.nvidia.com/hpc-sdk/eula/index.html')

        default_cuda_version = self.cfg['default_cuda_version']
        if default_cuda_version is None:
            module_cuda_version_full = get_software_version('CUDA')
            if module_cuda_version_full is not None:
                default_cuda_version = '.'.join(module_cuda_version_full.split('.')[:2])
            else:
                error_msg = "A default CUDA version is needed for installation of NVHPC. "
                error_msg += "It can not be determined automatically and needs to be added manually. "
                error_msg += "You can edit the easyconfig file, "
                error_msg += "or use 'eb --try-amend=default_cuda_version=<version>'."
                raise EasyBuildError(error_msg)

        # Parse default_compute_capability from different sources (CLI has priority)
        ec_default_compute_capability = self.cfg['cuda_compute_capabilities']
        cfg_default_compute_capability = build_option('cuda_compute_capabilities')
        if cfg_default_compute_capability is not None:
            default_compute_capability = cfg_default_compute_capability
        elif ec_default_compute_capability and ec_default_compute_capability is not None:
            default_compute_capability = ec_default_compute_capability
        else:
            error_msg = "A default Compute Capability is needed for installation of NVHPC."
            error_msg += "Please provide it either in the easyconfig file like 'cuda_compute_capabilities=\"7.0\"',"
            error_msg += "or use 'eb --cuda-compute-capabilities=7.0' from the command line."
            raise EasyBuildError(error_msg)

        # Extract first element of default_compute_capability list, if it is a list
        if isinstance(default_compute_capability, list):
            _before_default_compute_capability = default_compute_capability
            default_compute_capability = _before_default_compute_capability[0]
            if len(_before_default_compute_capability) > 1:
                warning_msg = "Replaced list of compute capabilities {} ".format(_before_default_compute_capability)
                warning_msg += "with first element of list: {}".format(default_compute_capability)
                print_warning(warning_msg)

        # Remove dot-divider for CC; error out if it is not a string
        if isinstance(default_compute_capability, str):
            default_compute_capability = default_compute_capability.replace('.', '')
        else:
            raise EasyBuildError("Unexpected non-string value encountered for compute capability: %s",
                                 default_compute_capability)

        nvhpc_env_vars = {
            'NVHPC_INSTALL_DIR': self.installdir,
            'NVHPC_SILENT': 'true',
            'NVHPC_DEFAULT_CUDA': str(default_cuda_version),  # 10.2, 11.0
            'NVHPC_STDPAR_CUDACC': str(default_compute_capability),  # 70, 80; single value, no list!
            }
        cmd = "%s ./install" % ' '.join(['%s=%s' % x for x in sorted(nvhpc_env_vars.items())])
        run_cmd(cmd, log_all=True, simple=True)

        # make sure localrc uses GCC in PATH, not always the system GCC, and does not use a system g77 but gfortran
        install_abs_subdir = os.path.join(self.installdir, self.nvhpc_install_subdir)
        compilers_subdir = os.path.join(install_abs_subdir, "compilers")
        makelocalrc_filename = os.path.join(compilers_subdir, "bin", "makelocalrc")
        for line in fileinput.input(makelocalrc_filename, inplace='1', backup='.orig'):
            line = re.sub(r"^PATH=/", r"#PATH=/", line)
            sys.stdout.write(line)

        if LooseVersion(self.version) >= LooseVersion('22.9'):
            bin_subdir = os.path.join(compilers_subdir, "bin")
            cmd = "%s -x %s" % (makelocalrc_filename, bin_subdir)
        else:
            cmd = "%s -x %s -g77 /" % (makelocalrc_filename, compilers_subdir)
        run_cmd(cmd, log_all=True, simple=True)

        # If an OS libnuma is NOT found, makelocalrc creates symbolic links to libpgnuma.so
        # If we use the EB libnuma, delete those symbolic links to ensure they are not used
        if get_software_root("numactl"):
            for filename in ["libnuma.so", "libnuma.so.1"]:
                path = os.path.join(compilers_subdir, "lib", filename)
                if os.path.islink(path):
                    os.remove(path)

        if LooseVersion(self.version) < LooseVersion('21.3'):
            # install (or update) siterc file to make NVHPC consider $LIBRARY_PATH
            siterc_path = os.path.join(compilers_subdir, 'bin', 'siterc')
            write_file(siterc_path, SITERC_LIBRARY_PATH, append=True)
            self.log.info("Appended instructions to pick up $LIBRARY_PATH to siterc file at %s: %s",
                          siterc_path, SITERC_LIBRARY_PATH)

        # The cuda nvvp tar file has broken permissions
        adjust_permissions(self.installdir, stat.S_IWUSR, add=True, onlydirs=True)

    def sanity_check_step(self):
        """Custom sanity check for NVHPC"""
        prefix = self.nvhpc_install_subdir
        compiler_names = ['nvc', 'nvc++', 'nvfortran']

        files = [os.path.join(prefix, 'compilers', 'bin', x) for x in compiler_names]
        if LooseVersion(self.version) < LooseVersion('21.3'):
            files.append(os.path.join(prefix, 'compilers', 'bin', 'siterc'))

        custom_paths = {
            'files': files,
            'dirs': [os.path.join(prefix, 'compilers', 'bin'), os.path.join(prefix, 'compilers', 'lib'),
                     os.path.join(prefix, 'compilers', 'include'), os.path.join(prefix, 'compilers', 'man')]
        }

        custom_commands = ["%s -v" % compiler for compiler in compiler_names]

        if LooseVersion(self.version) >= LooseVersion('21'):
            # compile minimal example using -std=c++20 to catch issue where it picks up the wrong GCC
            # (as long as system gcc is < 9.0)
            # see: https://github.com/easybuilders/easybuild-easyblocks/pull/3240
            tmpdir = tempfile.mkdtemp()
            write_file(os.path.join(tmpdir, 'minimal.cpp'), NVHPC_MINIMAL_EXAMPLE)
            minimal_compiler_cmd = "cd %s && nvc++ -std=c++20 minimal.cpp -o minimal" % tmpdir
            custom_commands.append(minimal_compiler_cmd)

        super(EB_NVHPC, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def _nvhpc_extended_components(self, dirs, basepath, env_vars_dirs):
        """
        Extends `dirs` dict of key:environment_variables, value:list_of_directories with additional vars and dirs.
        The dictionary key for a new env var will be created if it doesn't exist.
        Also, the relative path specified in the `env_vars_dirs` dict is absolutized with the `basepath` prefix.
        """
        for env_var, folders in sorted(env_vars_dirs.items()):
            if env_var not in dirs:
                dirs[env_var] = []
            if not isinstance(folders, list):
                folders = [folders]
            for folder in folders:
                dirs[env_var].append(os.path.join(basepath, folder))

    def make_module_req_guess(self):
        """Prefix subdirectories in NVHPC install dir considered for environment variables defined in module file."""
        dirs = super(EB_NVHPC, self).make_module_req_guess()
        for key in dirs:
            dirs[key] = [os.path.join(self.nvhpc_install_subdir, 'compilers', d) for d in dirs[key]]

        # $CPATH should not be defined in module for NVHPC, it causes problems
        # cfr. https://github.com/easybuilders/easybuild-easyblocks/issues/830
        if 'CPATH' in dirs:
            self.log.info("Removing $CPATH entry: %s", dirs['CPATH'])
            del dirs['CPATH']

        # EasyBlock option parsing follows:
        # BYO Compilers:
        # Use NVHPC's libraries and tools with other, external compilers
        if self.cfg['module_byo_compilers']:
            if 'PATH' in dirs:
                del dirs["PATH"]
        # Own MPI:
        # NVHPC is shipped with a compiled OpenMPI installation
        # Enable it by setting according environment variables
        if self.cfg['module_nvhpc_own_mpi']:
            self.nvhpc_mpi_basedir = os.path.join(self.nvhpc_install_subdir, "comm_libs", "mpi")
            env_vars_dirs = {
                'PATH': 'bin',
                'CPATH': 'include',
                'LD_LIBRARY_PATH': 'lib'
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_mpi_basedir, env_vars_dirs)
        # Math Libraries:
        # NVHPC is shipped with math libraries (in a dedicated folder)
        # Enable them by setting according environment variables
        if self.cfg['module_add_math_libs']:
            self.nvhpc_math_basedir = os.path.join(self.nvhpc_install_subdir, "math_libs")
            env_vars_dirs = {
                'CPATH': 'include',
                'LD_LIBRARY_PATH': 'lib64'
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_math_basedir, env_vars_dirs)
        # GPU Profilers:
        # NVHPC is shipped with NVIDIA's GPU profilers (Nsight Compute/Nsight Systems)
        # Enable them by setting the according environment variables
        if self.cfg['module_add_profilers']:
            self.nvhpc_profilers_basedir = os.path.join(self.nvhpc_install_subdir, "profilers")
            env_vars_dirs = {
                'PATH': ['Nsight_Compute', 'Nsight_Systems/bin']
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_profilers_basedir, env_vars_dirs)
        # NCCL:
        # NVHPC is shipped with NCCL
        # Enable it by setting the according environment variables
        if self.cfg['module_add_nccl']:
            self.nvhpc_nccl_basedir = os.path.join(self.nvhpc_install_subdir, "comm_libs", "nccl")
            env_vars_dirs = {
                'CPATH': 'include',
                'LD_LIBRARY_PATH': 'lib'
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_nccl_basedir, env_vars_dirs)
        # NVSHMEM:
        # NVHPC is shipped with NVSHMEM
        # Enable it by setting the according environment variables
        if self.cfg['module_add_nvshmem']:
            self.nvhpc_nvshmem_basedir = os.path.join(self.nvhpc_install_subdir, "comm_libs", "nvshmem")
            env_vars_dirs = {
                'CPATH': 'include',
                'LD_LIBRARY_PATH': 'lib'
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_nvshmem_basedir, env_vars_dirs)
        # CUDA:
        # NVHPC is shipped with CUDA (possibly multiple versions)
        # Rather use this CUDA than an external CUDA (via $CUDA_HOME) by setting according environment variables
        if self.cfg['module_add_cuda']:
            self.nvhpc_cuda_basedir = os.path.join(self.nvhpc_install_subdir, "cuda")
            env_vars_dirs = {
                'PATH': 'bin',
                'LD_LIBRARY_PATH': 'lib64',
                'CPATH': 'include'
            }
            self._nvhpc_extended_components(dirs, self.nvhpc_cuda_basedir, env_vars_dirs)
        return dirs

    def make_module_extra(self):
        """Add environment variable for NVHPC location"""
        txt = super(EB_NVHPC, self).make_module_extra()
        txt += self.module_generator.set_environment('NVHPC', self.installdir)
        if LooseVersion(self.version) >= LooseVersion('22.7'):
            # NVHPC 22.7+ requires the variable NVHPC_CUDA_HOME for external CUDA. CUDA_HOME has been deprecated.
            if not self.cfg['module_add_cuda'] and get_software_root('CUDA'):
                txt += self.module_generator.set_environment('NVHPC_CUDA_HOME', os.getenv('CUDA_HOME'))
        return txt
