from easybuild.framework.easyconfig import CUSTOM, MANDATORY, BUILD
from easybuild.tools.filetools import run_cmd
from easybuild.easyblocks.generic.configuremake import ConfigureMake
import os

class Amber(ConfigureMake):

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

    def configure_step(self):
        #cmd = '%(preconfigopts)s AMBERHOME="%(installdir)s" ./configure --no-updates %(configopts)s' % {
        cmd = '%(preconfigopts)s AMBERHOME=`pwd` ./configure --no-updates %(configopts)s' % {
            'preconfigopts': self.cfg['preconfigopts'],
            'installdir': self.installdir,
            'configopts': self.cfg['configopts'],
        }
        run_cmd(cmd, log_all=True, simple=False)

    def patch_step(self, **kw):
        if self.cfg['patchlevels'] == "latest":
            run_cmd("AMBERHOME=`pwd` ./update_amber --update", log_all=True)
        else:
            for (tree, patch_level) in zip(['AmberTools', 'Amber'], self.cfg['patchlevels']):
                if patch_level == 0: continue
                cmd = "AMBERHOME=`pwd` ./update_amber --update-to %s/%s" % (tree, patch_level) 
                run_cmd(cmd, log_all=True)
        return super(Amber, self).patch_step(**kw)

    def test_step(self):
        run_cmd("AMBERHOME=`pwd` make test", log_all=True)

    def make_module_extra(self):
        """Add module entries specific to Amber/AmberTools"""
        txt = super(Amber, self).make_module_extra()
        #cmd = "AMBERHOME=`pwd` ./update_amber -v"
        #(out, _) = run_cmd(cmd, log_all=True, simple=False)
        #txt += self.moduleGenerator.set_environment('AMBER_VERSION', out)
        return txt

        
        
    #def install_step(self):
    #    """
    #    Create the installation in correct location
    #    - typical: make install
    #    """
    #
    #    cmd = "%s AMBERHOME=%s make install %s" % (
    #        self.cfg['preinstallopts'], self.installdir, self.cfg['installopts'])
    #
    #    (out, _) = run_cmd(cmd, log_all=True, simple=False)
    #    return out
    
    
# MPI_HOME=$EBROOTIMPI MKL_HOME=$EBROOTIMKL 
