from easybuild.framework.easyconfig import CUSTOM, MANDATORY, BUILD
from easybuild.tools.filetools import run_cmd
from easybuild.easyblocks.generic.configuremake import ConfigureMake
import os

class Amber(ConfigureMake):
    """Easyblock for building and installing Amber"""


    def __init__(self, *args, **kwargs):
        super(Amber, self).__init__(*args, **kwargs)
        self.already_extracted = False

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to ConfigureMake."""
        supersuperclass = super(ConfigureMake, ConfigureMake)
        extra_vars = dict(supersuperclass.extra_options(extra_vars))
        extra_vars.update({
            # 'Amber': [True, "Build Amber in addition to AmberTools", CUSTOM],
            'patchlevels': ["latest", "(AmberTools, Amber) updates to be applied", CUSTOM],
        })
        # Don't include the ConfigureMake extra options since this configure_step doesn't handle them
        return supersuperclass.extra_options(extra_vars)

    def extract_step(self):
        """Only extract from the tarball if this has not already been done."""
        if (self.already_extracted == True):
            cmd = '%(prebuildopts)s make clean' % {
                'prebuildopts': self.cfg['prebuildopts']
            }
            run_cmd(cmd, log_all=True, simple=False)
        else:
            super(Amber, self).extract_step()
            self.already_extracted = True

    def configure_step(self):
        #cmd = '%(preconfigopts)s AMBERHOME="%(installdir)s" ./configure --no-updates %(configopts)s' % {
        cmd = '%(preconfigopts)s %(prebuildopts)s ./configure --no-updates %(configopts)s' % {
            'prebuildopts': self.cfg['prebuildopts'],
            'preconfigopts': self.cfg['preconfigopts'],
            'installdir': self.installdir,
            'configopts': self.cfg['configopts']
        }
        run_cmd(cmd, log_all=True, simple=False)

    def patch_step(self, **kw):
        if self.cfg['patchlevels'] == "latest":
            cmd = "%(prebuildopts)s ./update_amber --update" % {
                'prebuildopts': self.cfg['prebuildopts']
            }
            run_cmd(cmd, log_all=True)
        else:
            for (tree, patch_level) in zip(['AmberTools', 'Amber'], self.cfg['patchlevels']):
                if patch_level == 0: continue
                cmd = "%s ./update_amber --update-to %s/%s" % (self.cfg['prebuildopts'], tree, patch_level) 
                run_cmd(cmd, log_all=True)
        return super(Amber, self).patch_step(**kw)

    def test_step(self):
        cmd = "%s make test" % (self.cfg['prebuildopts'])
        run_cmd(cmd, log_all=True)

    def make_module_extra(self):
        """Add module entries specific to Amber/AmberTools"""
        txt = super(Amber, self).make_module_extra()
        #cmd = "AMBERHOME=`pwd` ./update_amber -v"
        #(out, _) = run_cmd(cmd, log_all=True, simple=False)
        #txt += self.moduleGenerator.set_environment('AMBER_VERSION', out)
        return txt
        

    def install_step(self):
        """In Amber, installation is conflated with building,
        so that 'make install' is done during the build step."""
        pass
