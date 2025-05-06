import os

from easybuild.easyblocks.generic.cmakepythonpackage import CMakePythonPackage
from easybuild.easyblocks.generic.pythonpackage import PIP_INSTALL_CMD
from easybuild.tools.run import run_cmd
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import copy_dir

class EB_Basix(CMakePythonPackage):
    """Custom easyblock for Basix"""
    def build_step(self):
        """Build step need not be overridden"""
        super(EB_Basix, self).build_step()

        # Building 'lib64/libbasix.so'
        self.cfg['build_type'] = 'Release'
        self.cfg['srcdir'] = 'cpp'
        self.cfg['build_cmd'] = 'cmake --build %s/easybuild_obj' % self.builddir

    def install_step(self):
        """
        Purpose:
          1. Suppress the unwanted '--no-dep --ignore-cache' options of
             the 'cmake --install <path>' command
             Install the libbasix.so
          2. Install the Python interface
          3. Copy out lib the folder
        """
        self.cfg['installopts'] = ''
        self.log.info('Resetting "installopts" in basix.py')

        # step 1: Installing the C++ shared lib
        self.install_cmd = 'cmake --install %s' % self.start_dir
        self.log.info('Installing lib64/libbasix.so')

        # step 2: Installing the Python interface using PDM
        _namelower = self.name.lower()
        _loc_basix_dir = os.path.join(self.builddir, '%s-%s' % (_namelower, self.version))
        _pdm_cmd = 'pdm install --project %s' % _loc_basix_dir
        out, err = run_cmd(_pdm_cmd, simple=False, log_ok=True, log_all=True, trace=True)
        if err:
            raise EasyBuildError('Error running "%s". message: %s' % (_pdm_cmd, out))
        else:
            self.log.info('"%s" succeeded' % _pdm_cmd)

        # step 3: Copy out the new lib folder to the installation folder
        _loc_venv_dir = os.path.join(_loc_basix_dir, '.venv')
        _loc_venv_lib_dir = os.path.join(_loc_venv_dir, 'lib')
        copy_dir(_loc_venv_lib_dir, self.installdir, dirs_exist_ok=True)

        # self.install_cmd = _pip_cmd
        _pythonpath = os.environ.get('PYTHONPATH', '')
        os.environ['PYTHONPATH'] = ':'.join([os.path.join(self.installdir, self.pylibdir), _pythonpath])
        self.log.info('Extending PYTHONPATH to: "%s"' % os.environ['PYTHONPATH'])

        super(EB_Basix, self).install_step()
