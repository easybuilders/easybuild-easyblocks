"""
EasyBuild support for building and installing OpenBLAS, implemented as an easyblock

@author: Andrew Edmondson (University of Birmingham)
"""
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import POWER, get_cpu_architecture


class EB_OpenBLAS(ConfigureMake):
    """Support for building/installing OpenBLAS."""

    def build_step(self):
        """Custom build procedure for OpenBLAS."""

        if get_cpu_architecture() == POWER:
            # There doesn't seem to be a POWER9 option yet, but POWER8 should work.
            self.cfg['buildopts'] += ' TARGET=POWER8'

        super(EB_OpenBLAS, self).build_step()
