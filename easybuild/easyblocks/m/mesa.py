# This easyblock was created by the BEAR Software team at the University of Birmingham

from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class EB_Mesa(MesonNinja):
    def configure_step(self, cmd_prefix=''):
        """
        Customise the configopts based on the platform
        """
        arch = get_cpu_architecture()
        if arch == X86_64:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast,swr')
        elif arch == POWER:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast'")
        return super(EB_Mesa, self).configure_step(cmd_prefix=cmd_prefix)
