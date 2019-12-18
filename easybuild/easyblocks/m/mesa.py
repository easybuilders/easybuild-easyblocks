# This easyblock was created by the BEAR Software team at the University of Birmingham

from mesonninja import MesonNinja
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class Mesa(MesonNinja):
    def configure_step(self, cmd_prefix=''):
        """
        Customise the configopts based on the platform
        """
        arch = get_cpu_architecture()
        if arch == X86_64:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast,swr' -Dswr-arches=avx,avx2,skx,knl")
        elif arch == POWER:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast'")

