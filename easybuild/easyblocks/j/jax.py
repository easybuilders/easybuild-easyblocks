"""
EasyBuild support for building and installing JAX, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""
import os
import shutil
import stat

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, copy_file
from easybuild.tools.systemtools import POWER, get_cpu_architecture


class EB_JAX(EasyBlock):
    """Support for building/installing JAX."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Define extra easyconfig parameters specific to JAX."""
        extra = Binary.extra_options(extra_vars)
        extra.update({
            'templates': [[], "List of templates.", CUSTOM],
            'sysconfig': [None, "system.config file to install.", CUSTOM],
        })
        return extra

    def extract_step(self):
        """Extract JAX installation files."""
        EasyBlock.extract_step(self)

    def configure_step(self):
        """No configuration for JAX."""
        pass

    def build_step(self):
        """No build step for JAX."""
        cuda = get_software_root(dep['CUDA'])
        cudnn= get_software_root(dep['CuDNN'])
        bazel = get_software_root(dep['Bazel'])
        binutils = get_software_root(dep['binutils'])
        if self.cfg['prebuildopts'] is None:
            self.cfg['prebuildopts'] = 'export TF_CUDA_PATHS="{}" '.format(cuda)
            self.cfg['prebuildopts'] += 'GCC_HOST_COMPILER_PREFIX="{}/bin" '.format(binutils)
            # To prevent bazel builds on different hosts/architectures conflicting with each other
            # we'll set HOME, inside which Bazel puts active files (in ~/.cache/bazel/...)
            self.cfg['prebuildopts'] += 'HOME={}/fake_home && '.format(self.installdir)

        if self.cfg['build_cmd'] is None:
            self.cfg['build_cmd'] = 'python build/build.py'

        if self.cfg['buildopts'] is None:
            self.cfg['buildopts'] = ' --enable_cuda --cuda_path {} '.format(cuda)
            self.cfg['buildopts'] += '--cudnn_path {} '.format(cudnn)
            self.cfg['buildopts'] += '--bazel_path {}/bin/bazel '.format(bazel)
            # Tell Bazel to pass PYTHONPATH through to what it's building, so it can find scipy etc.
            self.cfg['buildopts'] += '--bazel_options=--action_env=PYTHONPATH '
            self.cfg['buildopts'] += '--noenable_mkl_dnn '
            if get_cpu_architecture() == POWER:
                # Tell Bazel to tell NVCC to tell the compiler to use -mno-float128
                self.cfg['buildopts'] += ('--bazel_options=--per_file_copt=.*cu\.cc.*'
                                          '@-nvcc_options=compiler-options=-mno-float128 ')

    def install_step(self):
        """Install JAX using install script."""

        if self.cfg['install_cmd'] is None:
            self.cfg['install_cmd'] = '(cd build && pip install --prefix {} .) &&'.format(self.installdir)
            self.cfg['install_cmd'] = 'pip install --prefix {} .'.format(self.installdir)

        raise IOError(self.cfg['modextravars'])

        super(EB_JAX, self).install_step()

        # copy license file
        lic_path = os.path.join(self.installdir, 'licences')
        try:
            shutil.copy2(self.cfg['license_file'], lic_path)
        except OSError as err:
            raise EasyBuildError("Failed to copy license file to %s: %s", lic_path, err)

        # copy templates
        templ_path = os.path.join(self.installdir, 'templates')
        for templ in self.cfg['templates']:
            path = self.obtain_file(templ, extension='qtf')
            if path:
                self.log.debug('Template file %s found' % path)
            else:
                raise EasyBuildError('No template file named %s found', templ)

            try:
                # use shutil.copy (not copy2) so that permissions of copied file match with rest of installation
                shutil.copy(path, templ_path)
            except OSError as err:
                raise EasyBuildError("Failed to copy template %s to %s: %s", templ, templ_path, err)

        # copy system.config if requested
        sysconf_path = os.path.join(self.installdir, 'system.config')
        if self.cfg['sysconfig'] is not None:
            path = self.obtain_file(self.cfg['sysconfig'], extension=False)
            if path:
                self.log.debug('system.config file %s found' % path)
            else:
                raise EasyBuildError('No system.config file named %s found', sysconf_path)

            copy_file(path, sysconf_path)
            adjust_permissions(sysconf_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH,
                               recursive=False, relative=False)

    def sanity_check_step(self):
        """Custom sanity check for JAX."""
        custom_paths = {
            'files': ['bin/ddt', 'bin/map'],
            'dirs': [],
        }
        super(EB_JAX, self).sanity_check_step(custom_paths=custom_paths)
