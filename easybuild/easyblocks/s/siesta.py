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
        build_vars += 'BLAS_LIBS="$LIBBLAS" LAPACK_LIBS="$LIBLAPACK" '
        build_vars += 'BLACS_LIBS="$LIBBLACS" SCALAPACK_LIBS="$LIBSCALAPACK"'

        self.cfg['prebuildopts'] = 'cd Obj && ' + cfg_cmd + ' && '
        self.cfg['buildopts'] = build_vars

        bins = ['Obj/siesta']

        if self.cfg['with_transiesta']:
            self.cfg['buildopts'] += ' && cd .. && mkdir Obj2 && cd Obj2 && '
            self.cfg['buildopts'] += cfg_cmd + ' && make transiesta ' + build_vars

            bins.extend(['Obj2/transiesta'])

        if self.cfg['with_utils']:
            self.cfg['buildopts'] += ' && cd ../Util && sh ./build_all.sh'

            bins.extend(['Util/Bands/eigfat2plot', 'Util/Bands/new.gnubands', 'Util/Bands/gnubands'])

            bins.extend(['Util/CMLComp/ccViz'])

            bins.extend(['Util/COOP/mprop', 'Util/COOP/dm_creator', 'Util/COOP/fat'])

            bins.extend(['Util/Contrib/APostnikov/eig2bxsf', 'Util/Contrib/APostnikov/xv2xsf',
                         'Util/Contrib/APostnikov/md2axsf', 'Util/Contrib/APostnikov/rho2xsf',
                         'Util/Contrib/APostnikov/vib2xsf', 'Util/Contrib/APostnikov/fmpdos'])

            bins.extend(['Util/Denchar/Examples/2dplot.py', 'Util/Denchar/Examples/surf.py',
                         'Util/Denchar/Src/denchar'])

            bins.extend(['Util/DensityMatrix/dm2cdf', 'Util/DensityMatrix/cdf2dm'])

            bins.extend(['Util/Eig2DOS/Eig2DOS'])

            bins.extend(['Util/Gen-basis/ionplot.sh', 'Util/Gen-basis/gen-basis', 'Util/Gen-basis/ioncat'])

            bins.extend(['Util/Grid/grid2cdf', 'Util/Grid/cdf2xsf', 'Util/Grid/cdf2grid', 'Util/Grid/grid2val',
                         'Util/Grid/grid2cube'])

            bins.extend(['Util/HSX/hsx2hs', 'Util/HSX/hs2hsx'])

            bins.extend(['Util/Helpers/get_chem_labels'])

            bins.extend(['Util/MPI_test/pi3'])

            bins.extend(['Util/Macroave/Src/macroave'])

            bins.extend(['Util/ON/lwf2cdf'])

            bins.extend(['Util/Optimizer/swarm', 'Util/Optimizer/simplex'])

            bins.extend(['Util/Projections/orbmol_proj'])

            bins.extend(['Util/STM/simple-stm/plstm'])

            bins.extend(['Util/SiestaSubroutine/FmixMD/Src/simple', 'Util/SiestaSubroutine/FmixMD/Src/driver',
                         'Util/SiestaSubroutine/FmixMD/Src/para'])

            bins.extend(['Util/TBTrans/tbtrans'])

            bins.extend(['Util/VCA/mixps', 'Util/VCA/fractional'])

            bins.extend(['Util/Vibra/Src/fcbuild', 'Util/Vibra/Src/vibrator'])

            bins.extend(['Util/WFS/readwf', 'Util/WFS/readwfx', 'Util/WFS/info_wfsx', 'Util/WFS/wfs2wfsx',
                         'Util/WFS/wfsx2wfs', 'Util/WFS/wfsnc2wfsx'])

            bins.extend(['Util/pdosxml/pdosxml'])

            bins.extend(['Util/pseudo-xml/xml2psf'])

            bins.extend(['Util/test-xml/test-xml'])

        self.cfg['files_to_copy'] = [(bins, 'bin')]

    def sanity_check_step(self):
        """Custom sanity check for Siesta."""

        bins = ['bin/siesta']

        if self.cfg['with_transiesta']:
            bins.extend(['bin/transiesta'])

        if self.cfg['with_utils']:
            bins.extend(['bin/' + util for util in 'eigfat2plot', 'new.gnubands', 'gnubands', 'ccViz', 'mprop',
                         'dm_creator', 'fat', 'eig2bxsf', 'xv2xsf', 'md2axsf', 'rho2xsf', 'vib2xsf', 'fmpdos',
                         '2dplot.py', 'surf.py', 'denchar', 'dm2cdf', 'cdf2dm', 'Eig2DOS', 'ionplot.sh', 'gen-basis',
                         'ioncat', 'grid2cdf', 'cdf2xsf', 'cdf2grid', 'grid2val', 'grid2cube', 'hsx2hs', 'hs2hsx',
                         'get_chem_labels', 'pi3', 'macroave', 'lwf2cdf', 'swarm', 'simplex', 'orbmol_proj', 'plstm',
                         'simple', 'driver', 'para', 'tbtrans', 'mixps', 'fractional', 'fcbuild', 'vibrator', 'readwf',
                         'readwfx', 'info_wfsx', 'wfs2wfsx', 'wfsx2wfs', 'wfsnc2wfsx', 'pdosxml', 'xml2psf', 'test-xml'
                         ])

        custom_paths = {
            'files': bins,
            'dirs': []
            }

        super(EB_Siesta, self).sanity_check_step(custom_paths=custom_paths)
