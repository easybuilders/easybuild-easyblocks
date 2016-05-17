##
# Copyright 2009-2016 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
EasyBuild support for Siesta, implemented as an easyblock

@author: Miguel Dias Costa (National university of Singapore)
"""

import easybuild.tools.toolchain as toolchain
from easybuild.framework.easyconfig import CUSTOM
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.easyblocks.generic.makecp import MakeCp


class EB_Siesta(MakeCp):
    """Support for building and installing Siesta."""

    @staticmethod
    def extra_options(extra_vars=None):
        """
        Define list of files or directories to be copied after make
        """
        extra = {
            'files_to_copy': [[], "List of files or dirs to copy", CUSTOM],
            'with_transiesta': [True, "Build transiesta", CUSTOM],
            'with_utils': [True, "Build all utils", CUSTOM],
        }
        if extra_vars is None:
            extra_vars = {}
        extra.update(extra_vars)
        return ConfigureMake.extra_options(extra_vars=extra)

    def __init__(self, *args, **kwargs):
        super(EB_Siesta, self).__init__(*args, **kwargs)

        cfg_cmd = '../Src/obj_setup.sh && ../Src/configure'
        if self.toolchain.options.get('usempi', None):
            cfg_cmd += ' --enable-mpi '

        build_vars = "COMP_LIBS='' "
        build_vars += 'BLAS_LIBS="$LIBBLAS" LAPACK_LIBS="$LIBLAPACK" BLACS_LIBS="$LIBBLACS" SCALAPACK_LIBS="$LIBSCALAPACK"'

        self.cfg['prebuildopts'] = 'cd Obj && ' + cfg_cmd + ' && '
        self.cfg['buildopts'] = build_vars
        bins = ['Obj/siesta']

        if self.cfg['with_transiesta']:
            self.cfg['buildopts'] += ' && cd .. && mkdir Obj2 && cd Obj2 && ' + cfg_cmd + ' && make transiesta ' + build_vars
            bins.extend(['Obj2/transiesta'])

        if self.cfg['with_utils']:
            self.cfg['buildopts'] += ' && cd ../Util && sh ./build_all.sh'
            bins.extend(['Util/Bands/eigfat2plot', 'Util/Bands/new.gnubands',
                         'Util/Bands/gnubands', 'Util/CMLComp/ccViz', 'Util/COOP/mprop', 'Util/COOP/dm_creator',
                         'Util/COOP/fat', 'Util/Contrib/APostnikov/eig2bxsf', 'Util/Contrib/APostnikov/xv2xsf',
                         'Util/Contrib/APostnikov/md2axsf', 'Util/Contrib/APostnikov/rho2xsf',
                         'Util/Contrib/APostnikov/vib2xsf', 'Util/Contrib/APostnikov/fmpdos',
                         'Util/Denchar/Examples/2dplot.py', 'Util/Denchar/Examples/surf.py', 'Util/Denchar/Src/denchar',
                         'Util/DensityMatrix/dm2cdf', 'Util/DensityMatrix/cdf2dm', 'Util/Eig2DOS/Eig2DOS',
                         'Util/Gen-basis/ionplot.sh', 'Util/Gen-basis/gen-basis', 'Util/Gen-basis/ioncat',
                         'Util/Grid/grid2cdf', 'Util/Grid/cdf2xsf', 'Util/Grid/cdf2grid', 'Util/Grid/grid2val',
                         'Util/Grid/grid2cube', 'Util/HSX/hsx2hs', 'Util/HSX/hs2hsx', 'Util/Helpers/get_chem_labels',
                         'Util/MPI_test/pi3', 'Util/Macroave/Src/macroave', 'Util/ON/lwf2cdf', 'Util/Optimizer/swarm',
                         'Util/Optimizer/simplex', 'Util/Projections/orbmol_proj', 'Util/STM/simple-stm/plstm',
                         'Util/SiestaSubroutine/FmixMD/Src/simple', 'Util/SiestaSubroutine/FmixMD/Src/driver',
                         'Util/SiestaSubroutine/FmixMD/Src/para', 'Util/TBTrans/tbtrans', 'Util/VCA/mixps',
                         'Util/VCA/fractional', 'Util/Vibra/Src/fcbuild', 'Util/Vibra/Src/vibrator', 'Util/WFS/readwf',
                         'Util/WFS/readwfx', 'Util/WFS/info_wfsx', 'Util/WFS/wfs2wfsx', 'Util/WFS/wfsx2wfs',
                         'Util/WFS/wfsnc2wfsx', 'Util/pdosxml/pdosxml', 'Util/pseudo-xml/xml2psf',
                         'Util/test-xml/test-xml'])
            
        self.cfg['files_to_copy'] = [(bins, 'bin')]

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['bin/transiesta'])

        if self.cfg['with_utils']:
            bins.extend(['bin/tbtrans', 'bin/eigfat2plot', 'bin/new.gnubands', 'bin/gnubands',
                         'bin/ccViz', 'bin/mprop', 'bin/dm_creator', 'bin/fat', 'bin/eig2bxsf', 'bin/xv2xsf', 'bin/md2axsf',
                         'bin/rho2xsf', 'bin/vib2xsf', 'bin/fmpdos', 'bin/2dplot.py', 'bin/surf.py', 'bin/denchar', 'bin/dm2cdf',
                         'bin/cdf2dm', 'bin/Eig2DOS', 'bin/ionplot.sh', 'bin/gen-basis', 'bin/ioncat', 'bin/grid2cdf',
                         'bin/cdf2xsf', 'bin/cdf2grid', 'bin/grid2val', 'bin/grid2cube', 'bin/hsx2hs', 'bin/hs2hsx',
                         'bin/get_chem_labels', 'bin/pi3', 'bin/macroave', 'bin/lwf2cdf', 'bin/swarm', 'bin/simplex',
                         'bin/orbmol_proj', 'bin/plstm', 'bin/simple', 'bin/driver', 'bin/para', 'bin/tbtrans', 'bin/mixps',
                         'bin/fractional', 'bin/fcbuild', 'bin/vibrator', 'bin/readwf', 'bin/readwfx', 'bin/info_wfsx',
                         'bin/wfs2wfsx', 'bin/wfsx2wfs', 'bin/wfsnc2wfsx', 'bin/pdosxml', 'bin/xml2psf', 'bin/test-xml'])

        custom_paths = {
            'files': bins,
            'dirs': []
            }

        super(EB_Siesta, self).sanity_check_step(custom_paths=custom_paths)
