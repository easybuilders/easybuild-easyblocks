from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
import easybuild.tools.environment as env


class EB_DeepSpeed(PythonPackage):
    """Custom easyblock for DeepSpeed"""

    @staticmethod
    def extra_options():
        """Change some defaults for easyconfig parameters."""
        extra_vars = PythonPackage.extra_options()
        extra_vars['use_pip'][0] = True
        extra_vars['download_dep_fail'][0] = True
        extra_vars['sanity_pip_check'][0] = True
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize DeepSpeed easyblock."""
        super().__init__(*args, **kwargs)

        dep_names = set(dep['name'] for dep in self.cfg.dependencies())

        # require that PyTorch is listed as dependency
        if 'PyTorch' not in dep_names:
            raise EasyBuildError('PyTorch not found as a dependency')

        # enable building with GPU support if CUDA is included as dependency
        if 'CUDA' in dep_names:
            self.with_cuda = True
        else:
            self.with_cuda = False

    @property
    def cuda_compute_capabilities(self):
        return self.cfg['cuda_compute_capabilities'] or build_option('cuda_compute_capabilities')

    def configure_step(self):
        """Set up DeepSpeed config"""

        if self.with_cuda:
            # https://github.com/microsoft/DeepSpeed/issues/3358
            env.setvar('NVCC_PREPEND_FLAGS', '--forward-unknown-opts')

            if self.cuda_compute_capabilities:
                # specify CUDA compute capabilities via $TORCH_CUDA_ARCH_LIST
                env.setvar('TORCH_CUDA_ARCH_LIST', ';'.join(self.cuda_compute_capabilities))

        # By default prebuild all opts with a few exceptions
        # http://www.deepspeed.ai/tutorials/advanced-install/#pre-install-deepspeed-ops
        # > DeepSpeed will only install any ops that are compatible with your machine
        env.setvar('DS_BUILD_OPTS', '1')

        # These have bothersome dependencies
        env.setvar('DS_BUILD_SPARSE_ATTN', '0')  # requires PyTorch<2.0, triton==1.0.0
        env.setvar('DS_BUILD_EVOFORMER_ATTN', '0')  # requires PyTorch<2.0, triton==1.0.0
        env.setvar('DS_BUILD_CUTLASS_OPS', '0')  # requires dskernels
        env.setvar('DS_BUILD_RAGGED_DEVICE_OPS', '0')  # requires dskernels

        super().configure_step()
