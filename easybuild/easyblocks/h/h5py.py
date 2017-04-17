from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd

class h5py(PythonPackage):
    """Support for installing the h5py Python package."""

    def configure_step(self):
        super(h5py, self).configure_step()
          
        # adding mpi support
        run_cmd("python setup.py configure --mpi")

    def sanity_check_step(self, *args, **kwargs):
        return
