"""
Support for building and installing AOMP - AMD OpenMP compiler, implemented as
an EasyBlock

@author: Jorgen Nordmoen (University Center for Information Technology - UiO)
"""

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.modules import get_software_root

AOMP_ALL_COMPONENTS = ['roct', 'rocr', 'project', 'libdevice', 'openmp',
                       'extras', 'pgmath', 'flang', 'flang_runtime', 'comgr',
                       'rocminfo', 'vdi', 'hipvdi', 'ocl', 'rocdbgapi',
                       'rocgdb', 'roctracer', 'rocprofiler']
AOMP_DEFAULT_COMPONENTS = ['roct', 'rocr', 'project', 'libdevice', 'openmp',
                           'extras', 'pgmath', 'flang', 'flang_runtime',
                           'comgr', 'rocminfo']
AOMP_X86_COMPONENTS = ['vdi', 'hipvdi', 'ocl']
AOMP_DBG_COMPONENTS = ['rocdbgapi', 'rocgdb']
AOMP_PROF_COMPONENTS = ['roctracer', 'rocprofiler']


class EB_AOMP(Binary):
    """Support for installing AOMP"""

    @staticmethod
    def extra_options():
        extra_vars = Binary.extra_options()
        extra_vars.update({
            'components': [None, "AOMP components to build. Possible components: " +
                           ', '.join(AOMP_ALL_COMPONENTS), CUSTOM],
            'cuda_compute_capabilities': [[], "List of CUDA compute capabilities to build with", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables for Clang."""
        super(EB_AOMP, self).__init__(*args, **kwargs)
        self.cfg['extract_sources'] = True
        self.cfg['dontcreateinstalldir'] = True

    def configure_step(self):
        """Configure AOMP build and let 'Binary' install"""
        # Setup install command
        self.cfg['install_cmd'] = './aomp/bin/build_aomp.sh'
        # Setup 'preinstallopts'
        version_major = self.version.split('.')[0]
        install_options = [
            f'AOMP={self.installdir}',
            f'AOMP_REPOS="{self.builddir}/aomp{version_major}"',
            f'AOMP_CMAKE={get_software_root("CMake")}/bin/cmake',
            'AOMP_CHECK_GIT_BRANCH=0',
            'AOMP_APPLY_ROCM_PATCHES=0',
            'AOMP_STANDALONE_BUILD=1',
        ]
        if self.cfg['parallel']:
            install_options.append(f'NUM_THREADS={self.cfg["parallel"]}')
        else:
            install_options.append('NUM_THREADS=1')
        # Check if CUDA is loaded and alternatively build CUDA backend
        if get_software_root('CUDA') or get_software_root('CUDAcore'):
            cuda_root = get_software_root('CUDA') or get_software_root('CUDAcore')
            install_options.append('AOMP_BUILD_CUDA=1')
            install_options.append(f'CUDA="{cuda_root}"')
            # Use the commandline / easybuild config option if given, else use
            # the value from the EC (as a default)
            cuda_cc = build_option('cuda_compute_capabilities')
            cuda_cc = cuda_cc or self.cfg['cuda_compute_capabilities']
            if not cuda_cc:
                raise EasyBuildError("CUDA module was loaded, "
                                     "indicating a build with CUDA, "
                                     "but no CUDA compute capability "
                                     "was specified!")
            # Convert '7.0' to '70' format
            cuda_cc = [cc.replace('.', '') for cc in cuda_cc]
            install_options.append(f'NVPTXGPUS="{",".join(cuda_cc)}"')
        else:
            # Explicitly disable CUDA
            install_options.append('AOMP_BUILD_CUDA=0')
        # Combine install instructions above into 'preinstallopts'
        self.cfg['preinstallopts'] = ' '.join(install_options)
        # Setup components for install
        components = self.cfg.get('components', None)
        # If no components were defined we use the default
        if not components:
            components = AOMP_DEFAULT_COMPONENTS
            # NOTE: The following has not been tested properly and is therefore
            # removed
            #
            # Add X86 components if correct architecture
            # if get_cpu_architecture() == X86_64:
            #     components.extend(AOMP_X86_COMPONENTS)
        # Only build selected components
        self.cfg['installopts'] = 'select ' + ' '.join(components)
