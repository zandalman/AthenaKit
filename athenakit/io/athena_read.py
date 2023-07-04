import numpy as np
import re

### Read files ###

# Read .hst files and return dict of 1D arrays.
def hst(filename):
    data = {}
    with open(filename, 'r') as data_file:
        line = data_file.readline()
        if (line != '# Athena++ history data\n'):
            raise TypeError(f"Bad file format \"{line.decode('utf-8')}\" ")
        header = data_file.readline()
        data_names = re.findall(r'\[\d+\]=(\S+)', header)
        if len(data_names) == 0:
            raise RuntimeError('Could not parse header')
    # Read data
    arr=np.loadtxt(filename).T
    # Make time monotonic increasing
    mono=np.minimum.accumulate(arr[0][::-1])[::-1]
    locs=np.append(mono[:-1]<mono[1:],True)
    # Make dictionary of results
    for i,name in enumerate(data_names):
        data[name]=arr[i][locs]
    return data
