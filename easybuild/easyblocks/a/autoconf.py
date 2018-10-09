"""
EasyBuild support for Autoconf, implemented as an easyblock.
"""
import os
import subprocess
from easybuild.easyblocks.generic.configuremake import ConfigureMake


class EB_Autoconf(ConfigureMake):
    """Support for building and installing Autoconf."""

    def configure_step(self, cmd_prefix=''):
        """If running on IBM Power then we need to specify the BUILD type"""
        arch = subprocess.check_output(['uname', '-m']).strip()
        if arch == 'ppc64le':
            if 'configopts' not in self.cfg:
                self.cfg['configopts'] = ''
            self.cfg['configopts'] += ' --build=ppc64le '

        super(EB_Autoconf, self).configure_step(cmd_prefix)

