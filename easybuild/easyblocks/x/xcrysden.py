##
# Copyright 2009-2020 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
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
EasyBuild support for building and installing XCrySDen, implemented as an easyblock

@author: Kenneth Hoste (Ghent University)
"""
import fileinput
import os
import re
import shutil
import sys

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.run import run_cmd
from easybuild.tools.filetools import read_file, write_file
from easybuild.tools.modules import get_software_root, get_software_version

def get_library_root(libname):
    """ Find directory for liblibname.so or liblibname.a in $LIBRARY_PATH """
    if os.getenv("EBROOTGENTOO"):
        return os.getenv("EBROOTGENTOO")
    else:
        library_path = os.getenv('LIBRARY_PATH').split(':')
        for path in library_path:
            if (os.path.exists(os.path.join(path, 'lib%s.so'%libname)) or
                os.path.exists(os.path.join(path, 'lib%s.a'%libname))):
                return path
    return ""

class EB_XCrySDen(ConfigureMake):
    """Support for building/installing XCrySDen."""

    def __init__(self, *args, **kwargs):
        """Initialisation of custom class variables for XCrySDen"""
        super(EB_XCrySDen, self).__init__(*args, **kwargs)
        self.tclroot = self.tclver = self.tkroot = self.tkver = 'UNKNOWN'

    def configure_step(self):
        """
        Check required dependencies, configure XCrySDen build by patching Make.sys file
        and set make target and installation prefix.
        """

        # figure out tcl/tk version
        out, err = run_cmd("echo 'puts $tcl_version;exit 0' | tclsh", log_all=True, simple=False)
        self.tclver = out.strip()
        self.tkver = self.tclver

        # check dependencies
        deps = ["GL", "tcl%s" % self.tclver, "tk%s" % self.tkver]
        for dep in deps:
            if not get_library_root(dep):
                raise EasyBuildError("Module for dependency with lib%s not loaded.", dep)

        # copy template Make.sys to apply_patch
        makesys_tpl_file = os.path.join("system", "Make.sys-shared")
        makesys_file = "Make.sys"
        try:
            shutil.copy2(makesys_tpl_file, makesys_file)
        except OSError as err:
            raise EasyBuildError("Failed to copy %s: %s", makesys_tpl_file, err)

        self.tclroot = get_library_root("tcl%s" % self.tclver)
        self.tkroot = get_library_root("tk%s" % self.tkver)

        # patch Make.sys
        settings = {
                    # USE_INTERP_RESULT re-enables a API in the Tcl headers that was dropped in Tcl >= 8.6.
                    # https://www.tcl.tk/man/tcl8.6/TclLib/Interp.htm
                    #'CFLAGS': os.getenv('CFLAGS') + ' -DUSE_INTERP_RESULT ',
                    'CFLAGS': os.getenv('CFLAGS'),
                    'CC': os.getenv('CC'),
                    'FFLAGS': os.getenv('F90FLAGS'),
                    'FC': os.getenv('F90'),
                    'TCL_LIB': "-ltcl%s" % self.tclver,
                    'TCL_INCDIR': "",
                    'TK_LIB': "-ltk%s" % self.tkver,
                    'TK_INCDIR': "",
                    'GLU_LIB': "-lGLU",
                    'GL_LIB': "-lGL",
                    'GL_INCDIR': "",
                    'FFTW3_LIB': "-L%s %s -L%s %s" % (os.getenv('FFTW_LIB_DIR'), os.getenv('LIBFFT'),
                                                      os.getenv('LAPACK_LIB_DIR'), os.getenv('LIBLAPACK_MT')),
                    'FFTW3_INCDIR': "-I%s" % os.getenv('FFTW_INC_DIR'),
                    'COMPILE_TCLTK': 'no',
                    'COMPILE_MESA': 'no',
                    'COMPILE_FFTW': 'no',
                    'COMPILE_MESCHACH': 'no'
                   }

        # compatibility flag for tcl8.6
        if self.tclver == '8.6':
            settings['CFLAGS'] += ' -DUSE_INTERP_RESULT'

        mesa_root = get_software_root('Mesa')
        if mesa_root:
            settings['GLU_LIB'] = "-L%s/lib -lGLU" % mesa_root
            settings['GL_LIB'] = "-L%s/lib -lGL" % mesa_root
            settings['GL_INCDIR'] = "-I%s/include" % mesa_root

        togl_root = get_software_root("Togl")
        if togl_root:
            togl = {'root': togl_root, 'ver': get_software_version("Togl")}
            settings['TOGL_LIB'] = "-L%(root)s/lib/Togl%(ver)s -lTogl%(ver)s" % togl
            settings['TOGL_INCDIR'] = "-I%(root)s/include" % togl

        for line in fileinput.input(makesys_file, inplace=1, backup='.orig'):
            # set config parameters
            for (key, value) in list(settings.items()):
                regexp = re.compile(r'^%s(\s+=).*' % key)
                if regexp.search(line):
                    line = regexp.sub('%s\\1 %s' % (key, value), line)
                    # remove replaced key/value pairs
                    settings.pop(key)
            sys.stdout.write(line)

        # append remaining key/value pairs
        makesys_file_txt = '\n'.join("%s = %s" % s for s in sorted(settings.items()))
        write_file(makesys_file, makesys_file_txt, append=True)

        self.log.debug("Patched Make.sys: %s" % read_file(makesys_file))

        # set make target to 'xcrysden', such that dependencies are not downloaded/built
        self.cfg.update('buildopts', 'xcrysden')

        # set installation prefix
        self.cfg.update('preinstallopts', 'prefix=%s' % self.installdir)

    # default 'make' and 'make install' should be fine

    def sanity_check_step(self):
        """Custom sanity check for XCrySDen."""

        binfiles = [os.path.join('bin', x) for x in ['ptable', 'pwi2xsf', 'pwo2xsf', 'unitconv', 'xcrysden']]
        libfiles = ['atomlab', 'calplane', 'cube2xsf', 'fhi_coord2xcr', 'fhi_inpini2ftn34',
                    'fracCoor', 'fsReadBXSF', 'ftnunit', 'gengeom', 'kPath', 'multislab',
                    'nn', 'pwi2xsf', 'pwi2xsf_old', 'pwKPath', 'recvec', 'savestruct',
                    'str2xcr', 'wn_readbakgen', 'wn_readbands', 'xcrys', 'xctclsh', 'xsf2xsf']

        custom_paths = {
            'files': binfiles + [os.path.join('lib', self.name.lower() + '-' + self.version, x) for x in libfiles],
            'dirs': [],
        }

        super(EB_XCrySDen, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set extra environment variables in module file."""
        txt = super(EB_XCrySDen, self).make_module_extra()

        tclpath = os.path.join(self.tclroot, "tcl%s" % self.tclver)
        txt += self.module_generator.set_environment('TCL_LIBRARY', tclpath)
        tkpath = os.path.join(self.tkroot, "tk%s" % self.tkver)
        txt += self.module_generator.set_environment('TK_LIBRARY', tkpath)

        return txt
