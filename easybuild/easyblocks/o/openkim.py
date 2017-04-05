##
# Copyright 2009-2017 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
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
EasyBuild support for building and installing Python, implemented as an easyblock

@author: Jakob Schiotz (Tech. Univ. Denmark)
"""

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
import urllib2
import json

class EB_OpenKIM(ConfigureMake):
    def build_step(self, verbose=False, path=None):
        """
        Start the actual build
        """
        # Build the API.
        self.log.info("Building the OpenKIM API")
        out1 = super(EB_OpenKIM, self).build_step(verbose=verbose, path=path)
        
        # Download all models
        self.log.info("Downloading all OpenKIM models")
        out2 = self.download_kim_models(verbose, path)

        # Build the models
        self.log.info("Building the OpenKIM models")
        out3 = super(EB_OpenKIM, self).build_step(verbose=verbose, path=path)
        
        return out1+out2+out3

    def download_kim_models(self, verbose, path):
        """Download the OpenKIM models."""
        # Unfortunately, make add-OpenKIM is currenlty broken.
        #cmd = "%s make %s add-OpenKIM" % (self.cfg['prebuildopts'], self.cfg['buildopts'])
        #(out, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)

        # We have to do this one model at a time.
        query = '&fields={"kimcode":1,"kim-api-version":1}&database=obj&query={"type":"mo"}'
        url = 'https://query.openkim.org/api'
        timeout = build_option('download_timeout')
        if timeout is None:
            # default to 10sec timeout if none was specified
            # default system timeout may be infinite (?)
            timeout = 10        
        # We should maybe do some error handling here?
        url_fd = urllib2.urlopen(url, data=query, timeout=timeout)
        models = json.loads(url_fd.read())
        models = [x['kimcode'] for x in models if x['kim-api-version'] >= "1.6"]
        self.log.info("Preparing to download and compile %d models." % (len(models),))
        out = ''
        for model in models:
            cmd = "%s make %s add-%s" % (self.cfg['prebuildopts'], 
                                         self.cfg['buildopts'],
                                         model)
            (out2, _) = run_cmd(cmd, path=path, log_all=True, simple=False, log_output=verbose)
            out = out + out2
        return out
