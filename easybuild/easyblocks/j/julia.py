from easybuild.framework.easyconfig import CUSTOM, MANDATORY, BUILD
from easybuild.tools.filetools import run_cmd
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.config import source_paths
from easybuild.tools.filetools import mkdir
import os, os.path

class EB_Julia(ConfigureMake):

    def configure_step(self):
        # Writing a Make.user file, as recommended in the Julia documentation
        srcpath = os.path.join(source_paths()[0], self.name[0].lower(), self.name, 'deps')
        prefix = self.installdir
        assert not self.cfg['preconfigopts'], "preconfigopts not supported for Julia"
        configopts = self.cfg['configopts']
        f = open('Make.user', 'a')
        f.write("""
prefix=%(prefix)s

# Use libraries available on the system instead of building them

%(configopts)s

""" % vars())
        f.close()
