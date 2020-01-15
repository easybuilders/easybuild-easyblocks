# This easyblock was created by the BEAR Software team at the University of Birmingham
import os
from easybuild.easyblocks.generic.mesonninja import MesonNinja
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture


class EB_Mesa(MesonNinja):
    def configure_step(self, cmd_prefix=''):
        """
        Customise the configopts based on the platform
        """
        arch = get_cpu_architecture()
        if os.environ.get('BB_CPU') == 'sandybridge':
            self.cfg.update('configopts', "-Dgallium-drivers='swrast'")
        elif arch == X86_64:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast,swr'")
        elif arch == POWER:
            self.cfg.update('configopts', "-Dgallium-drivers='swrast'")
        return super(EB_Mesa, self).configure_step(cmd_prefix=cmd_prefix)
