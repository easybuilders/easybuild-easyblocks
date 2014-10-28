##
#
# CeCILL-B FREE SOFTWARE LICENSE AGREEMENT
#
# This Agreement is a Free Software license agreement that is the result
# of discussions between its authors in order to ensure compliance with
# the two main principles guiding its drafting:
#
#     * firstly, compliance with the principles governing the distribution
#       of Free Software: access to source code, broad rights granted to
#       users,
#     * secondly, the election of a governing law, French law, with which
#       it is conformant, both as regards the law of torts and
#       intellectual property law, and the protection that it offers to
#    both authors and holders of the economic rights over software.
#
# Copyright:: Copyright 2014 - EDF
# Authors::   EDF CCN HPC <dsp-cspito-ccn-hpc@edf.fr>
# License::   CeCILL-B (see http://cecill.info/licences.en.html for more information)
#
##
"""
EasyBuild support for building and installing Code_Aster, implemented as an easyblock

@author: EDF CCN HPC
@author: Kenneth Hoste (Ghent University)
"""

import os
import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.modules import get_software_root
from easybuild.tools import toolchain
from easybuild.tools.filetools import run_cmd
from easybuild.tools.filetools import write_file


class EB_CODE_underscore_ASTER(ConfigureMake):
    """Support for building/installing CODE ASTER."""

    def inplace_change(filename, old_string, new_string):
        s=open(filename).read()
        s=s.replace(old_string,  new_string)
        f=open(filename, 'w')
        f.write(s)
        f.flush()
        f.close()

    def configure_step(self):
        """Configure CODE ASTER by modifying setup.cfg when Intel compilers are used."""

        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.INTELCOMP:  #@UndefinedVariable
        # set configure options in setup.cfg
            setup_cfg_params = {
            "PREFER_COMPILER = 'GNU'" : "PREFER_COMPILER = 'Intel'",
            "#PREFER_COMPILER_aster = 'Intel'" : "PREFER_COMPILER_aster = 'Intel'",
            "#PREFER_COMPILER_mumps = PREFER_COMPILER_aster" : "PREFER_COMPILER_mumps = PREFER_COMPILER_aster",
            "#PREFER_COMPILER_metis = PREFER_COMPILER_aster" : "PREFER_COMPILER_metis = PREFER_COMPILER_aster",
            }
            for (key, val) in setup_cfg_params.items():
                inplace_change(setup.cfg, key, val)
        elif comp_fam == toolchain.GCC:  #@UndefinedVariable
        # Don't change anything in setup.cfg
          f=open('setup.cfg','a')
#          text="MATHLIB='-L/home/greg/.local/easybuild/software/ATLAS/3.8.4-gompi-1.1.1-no-OFED-LAPACK-3.4.0/lib -llapack -lf77blas -lcblas -latlas'"
#          text = "MATHLIB = '-L%s %s' % (os.environ('LAPACK_LIB_DIR'), os.environ('LIBLAPACK'))"
          text = "MATHLIB='-L%s/lib -llapack -lf77blas -lcblas -latlas'" % get_software_root('ATLAS')
          f.write(text)
          f.close()
#WAIT          txt = "MATHLIB = '-L%s %s' % (os.environ('LAPACK_LIB_DIR'), os.environ('LIBLAPACK'))"
#WAIT          write_file('setup.cfg', txt, append=True)
        else:
            self.log.error("Unknown compiler family, don't know to prepare for building with specified toolchain.")


    def build_step(self):
        """No build procedure for Code_Aster. See install_step."""

        pass


    def install_step(self):
        """
        Build CODE_ASTER using 'python setup.py install --noprompt --prefix=$ASTER_ROOT'
        """
        env.setvar('ASTERROOT', self.cfg['start_dir'])
        try:
            os.chdir(self.cfg['start_dir'])
        except OSError, err:
            self.log.error("Failed to change to %s: %s" % (self.cfg['start_dir'], err))

        cmd = "python setup.py install --noprompt --prefix=% s" % self.installdir
        run_cmd(cmd, log_all=True, simple=True, log_output=True)


    def sanity_check_step(self):
        """Custom sanity check for CODE_ASTER."""

        custom_paths = {
                        'files': ['bin/%s' % x for x in ["eficasQt", "eficas", "as_run", "astk", "bsf",
                                                         "parallel_cp", "codeaster-run", "show", "get",
                                                         "showop", "as_client", "codeaster-client"]] +
                                 ['outils/%s' % x for x in ["gmsh", "gibi", "eficasQt", "pmetis", "kmetis",
                                                          "homard"]],
                        'dirs':[]
                        }

        super(EB_CODE_underscore_ASTER, self).sanity_check_step(custom_paths)



