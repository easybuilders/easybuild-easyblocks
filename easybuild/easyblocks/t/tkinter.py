##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing Tkinter. This is the Python core
module to use Tcl/Tk.

@author: Adam Huffman (The Francis Crick Institute)
@author: Ward Poelmans (Free University of Brussels)
@author: Kenneth Hoste (HPC-UGent)
"""
import glob
import os
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.easyblocks.python import EB_Python
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import move_file, remove_dir
from easybuild.tools.modules import get_software_root
from easybuild.tools.systemtools import get_shared_lib_ext


class EB_Tkinter(EB_Python):
    """Support for building/installing the Python Tkinter module
    based on the normal Python module. We build a normal python
    but only install the Tkinter bits.
    """

    @staticmethod
    def extra_options():
        """Disable EBPYTHONPREFIXES."""
        extra_vars = EB_Python.extra_options()
        # Not used for Tkinter
        del extra_vars['ebpythonprefixes']

        return extra_vars

    def __init__(self, *args, **kwargs):
        """Initialize Tkinter-specific variables."""
        super(EB_Tkinter, self).__init__(*args, **kwargs)
        self.tkinter_so_basename = None

    def configure_step(self):
        """Check for Tk before configuring"""
        tk = get_software_root('Tk')
        if not tk:
            raise EasyBuildError("Tk is mandatory to build Tkinter")

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        # Use a temporary install directory, as we only want the Tkinter part of the full install.
        self.orig_installdir = self.installdir
        self.installdir = tempfile.mkdtemp(dir=self.builddir)
        super(EB_Tkinter, self).configure_step()

    def install_step(self):
        """Install python but only keep the bits we need"""
        super(EB_Tkinter, self).install_step()

        if LooseVersion(self.version) >= LooseVersion('3'):
            tklibdir = "tkinter"
        else:
            tklibdir = "lib-tk"

        self.tkinter_so_basename = self.get_tkinter_so_basename(False)
        source_pylibdir = os.path.dirname(os.path.join(self.installdir, det_pylibdir()))

        # Reset the install directory and remove it if it already exists. It will not have been removed automatically
        # at the start of the install step, as self.installdir pointed at the temporary install directory.
        self.installdir = self.orig_installdir
        remove_dir(self.installdir)

        dest_pylibdir = os.path.join(self.installdir, det_pylibdir())

        move_file(os.path.join(source_pylibdir, tklibdir), os.path.join(dest_pylibdir, tklibdir))
        move_file(os.path.join(source_pylibdir, "lib-dynload", self.tkinter_so_basename),
                  os.path.join(dest_pylibdir, self.tkinter_so_basename))

    def get_tkinter_so_basename(self, in_final_dir):
        pylibdir = os.path.join(self.installdir, det_pylibdir())
        shlib_ext = get_shared_lib_ext()
        if in_final_dir:
            # The build has already taken place so the file will have been moved into the final pylibdir
            tkinter_so = os.path.join(pylibdir, '_tkinter*.' + shlib_ext)
        else:
            tkinter_so = os.path.join(os.path.dirname(pylibdir), 'lib-dynload', '_tkinter*.' + shlib_ext)
        tkinter_so_hits = glob.glob(tkinter_so)
        if len(tkinter_so_hits) != 1:
            raise EasyBuildError("Expected to find exactly one _tkinter*.so: %s", tkinter_so_hits)
        tkinter_so_basename = os.path.basename(tkinter_so_hits[0])

        return tkinter_so_basename

    def sanity_check_step(self):
        """Custom sanity check for Python."""
        if LooseVersion(self.version) >= LooseVersion('3'):
            tkinter = 'tkinter'
        else:
            tkinter = 'Tkinter'
        custom_commands = ["python -s -c 'import %s'" % tkinter]

        if not self.tkinter_so_basename:
            self.tkinter_so_basename = self.get_tkinter_so_basename(True)

        custom_paths = {
            'files': [os.path.join(det_pylibdir(), self.tkinter_so_basename)],
            'dirs': ['lib']
        }
        super(EB_Python, self).sanity_check_step(custom_commands=custom_commands, custom_paths=custom_paths)

    def make_module_extra(self):
        """Set PYTHONPATH"""
        txt = super(EB_Tkinter, self).make_module_extra()
        txt += self.module_generator.prepend_paths('PYTHONPATH', det_pylibdir())

        return txt
