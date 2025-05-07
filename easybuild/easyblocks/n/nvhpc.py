##
# Copyright 2015-2025 Bart Oldeman
# Copyright 2016-2025 Forschungszentrum Juelich
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
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.modules import MODULE_LOAD_ENV_HEADERS, get_software_root, get_software_version
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
        architecture = f'Linux_{platform.uname()[4]}'
        self.install_subdir = os.path.join(architecture, self.version)

        # Set search paths for environment defined in module file
        self.module_load_environment.PATH = os.path.join(self.install_subdir, 'compilers', 'bin')
        self.module_load_environment.LD_LIBRARY_PATH = os.path.join(self.install_subdir, 'compilers', 'lib')
        self.module_load_environment.LIBRARY_PATH = os.path.join(self.install_subdir, 'compilers', 'lib')
        self.module_load_environment.CMAKE_PREFIX_PATH = os.path.join(self.install_subdir, 'compilers')
        self.module_load_environment.CMAKE_MODULE_PATH = os.path.join(self.install_subdir, 'cmake')
        self.module_load_environment.MANPATH = os.path.join(self.install_subdir, 'compilers', 'man')
        self.module_load_environment.XDG_DATA_DIRS = os.path.join(self.install_subdir, 'compilers', 'share')
        # compilers can find their own headers, unset $CPATH (and equivalents)
        self.module_load_environment.set_alias_vars(MODULE_LOAD_ENV_HEADERS, [])
        # BYO Compilers: remove NVHPC compilers from path, use NVHPC's libraries and tools with external compilers
        if self.cfg['module_byo_compilers']:
            self.module_load_environment.PATH.remove(os.path.join(self.install_subdir, 'compilers', 'bin'))
        # Own MPI: enable OpenMPI bundled in NVHPC
        if self.cfg['module_nvhpc_own_mpi']:
            mpi_basedir = os.path.join(self.install_subdir, "comm_libs", "mpi")
            self.module_load_environment.PATH.append(os.path.join(mpi_basedir, 'bin'))
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(mpi_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(mpi_basedir, 'include'))
        # Math Libraries: enable math libraries bundled in NVHPC
        if self.cfg['module_add_math_libs']:
            math_basedir = os.path.join(self.install_subdir, "math_libs")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(math_basedir, 'lib64'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(math_basedir, 'include'))
        # GPU Profilers: enable NVIDIA's GPU profilers (Nsight Compute/Nsight Systems)
        if self.cfg['module_add_profilers']:
            profilers_basedir = os.path.join(self.install_subdir, "profilers")
            self.module_load_environment.PATH.extend([
                os.path.join(profilers_basedir, 'Nsight_Compute'),
                os.path.join(profilers_basedir, 'Nsight_Systems', 'bin'),
            ])
        # NCCL: enable NCCL bundled in NVHPC
        if self.cfg['module_add_nccl']:
            nccl_basedir = os.path.join(self.install_subdir, "comm_libs", "nccl")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(nccl_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(nccl_basedir, 'include'))
        # NVSHMEM: enable NVSHMEM bundled in NVHPC
        if self.cfg['module_add_nvshmem']:
            nvshmem_basedir = os.path.join(self.install_subdir, "comm_libs", "nvshmem")
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(nvshmem_basedir, 'lib'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(nvshmem_basedir, 'include'))
        # CUDA: enable CUDA bundled in NVHPC
        if self.cfg['module_add_cuda']:
            cuda_basedir = os.path.join(self.install_subdir, "cuda")
            self.module_load_environment.PATH.append(os.path.join(cuda_basedir, 'bin'))
            self.module_load_environment.LD_LIBRARY_PATH.append(os.path.join(cuda_basedir, 'lib64'))
            for cpp_header in self.module_load_environment.alias(MODULE_LOAD_ENV_HEADERS):
                cpp_header.append(os.path.join(cuda_basedir, 'include'))

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
        run_shell_cmd(cmd)

        # make sure localrc uses GCC in PATH, not always the system GCC, and does not use a system g77 but gfortran
        install_abs_subdir = os.path.join(self.installdir, self.install_subdir)
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
        run_shell_cmd(cmd)

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
        prefix = self.install_subdir
        compiler_names = ['nvc', 'nvc++', 'nvfortran']

        files = [os.path.join(prefix, 'compilers', 'bin', x) for x in compiler_names]
        if LooseVersion(self.version) < LooseVersion('21.3'):
            files.append(os.path.join(prefix, 'compilers', 'bin', 'siterc'))

        custom_paths = {
            'files': files,
            'dirs': [os.path.join(prefix, 'compilers', 'bin'), os.path.join(prefix, 'compilers', 'lib'),
                     os.path.join(prefix, 'compilers', 'include'), os.path.join(prefix, 'compilers', 'man')]
        }

        custom_commands = []
        if not self.cfg['module_byo_compilers']:
            custom_commands = [f"{compiler} -v" for compiler in compiler_names]
            if LooseVersion(self.version) >= LooseVersion('21'):
                # compile minimal example using -std=c++20 to catch issue where it picks up the wrong GCC
                # (as long as system gcc is < 9.0)
                # see: https://github.com/easybuilders/easybuild-easyblocks/pull/3240
                tmpdir = tempfile.mkdtemp()
                write_file(os.path.join(tmpdir, 'minimal.cpp'), NVHPC_MINIMAL_EXAMPLE)
                minimal_compiler_cmd = f"cd {tmpdir} && nvc++ -std=c++20 minimal.cpp -o minimal"
                custom_commands.append(minimal_compiler_cmd)

        super(EB_NVHPC, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self):
        """Add environment variable for NVHPC location"""
        txt = super(EB_NVHPC, self).make_module_extra()
        txt += self.module_generator.set_environment('NVHPC', self.installdir)
        if LooseVersion(self.version) >= LooseVersion('22.7'):
            # NVHPC 22.7+ requires the variable NVHPC_CUDA_HOME for external CUDA. CUDA_HOME has been deprecated.
            if not self.cfg['module_add_cuda'] and get_software_root('CUDA'):
                txt += self.module_generator.set_environment('NVHPC_CUDA_HOME', os.getenv('CUDA_HOME'))
        return txt
