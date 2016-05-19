import numpy as np
from numpy import cos, sin

from openmdao.api import Component

from crm_data import crm_base_mesh


def rotate(mesh, thetas):
    """computes rotation matricies given mesh and rotation angles in degress"""

    le = mesh[0]
    te = mesh[1]

    n_points = len(le)

    rad_thetas = thetas*np.pi/180.

    mats = np.zeros((n_points, 3,3), dtype="complex")
    mats[:,0,0] = cos(rad_thetas)
    mats[:,0,2] = sin(rad_thetas)
    mats[:,1,1] = 1
    mats[:,2,0] = -sin(rad_thetas)
    mats[:,2,2] = cos(rad_thetas)

    le[:] = np.einsum("ikj, ij -> ik", mats, le-te)
    le += te

    return mesh


def sweep(mesh, angle):
    """shearing sweep angle. Positive sweeps back. """

    le = mesh[0]
    te = mesh[1]

    y0 = le[0,1]

    tan_theta = sin(np.radians(angle))
    dx = (le[:,1] - y0) * tan_theta

    le[:,0] += dx
    te[:,0] += dx

    return mesh


def stretch(mesh, length):
    """strech mesh in span-wise direction to reach specified length"""

    le = mesh[0]
    te = mesh[1]

    n_points = len(le)

    y_len = le[-1,1] - le[0,1]
    dy = (length-y_len)/(n_points-1)*np.arange(1,n_points)

    le[1:,1] += dy
    te[1:,1] += dy

    return mesh


def mirror(mesh, right_side=True):
    """Takes a half geometry and mirrors it across the symmetry plane.
    If right_side==True, it mirrors from right to left,
    assuming that the first point is on the symmetry plane. Else
    it mirrors from left to right, assuming the last point is on the
    symmetry plane."""

    n_points = mesh.shape[1]

    new_mesh = np.empty((2,2*n_points-1,3))

    mirror_y = np.ones(mesh.shape)
    mirror_y[:,:,1] *= -1.0

    if right_side:
        new_mesh[:,:n_points,:] = mesh[:,::-1,:]*mirror_y
        new_mesh[:,n_points:,:] = mesh[:,1:,:]
    else:
        new_mesh[:,:n_points,:] = mesh[:,::-1,:]
        new_mesh[:,n_points:,:] = mesh[:,1:,:]*mirror_y[:,1:,:]

    # shift so 0 is at the left wing tip (structures wants it that way)
    y0 = new_mesh[0,0,1]
    new_mesh[:,:,1] -= y0

    return new_mesh


def mesh_gen(n_points_inboard=2, n_points_outboard=2, mesh=crm_base_mesh):
    """
    builds the right hand side of the crm wing with specified number
    of inboard and outboard panels
    """

    # LE pre-yehudi
    s1 = (mesh[0,1,0] - mesh[0,0,0])/(mesh[0,1,1]-mesh[0,0,1])
    o1 = mesh[0,0,0]

    # TE pre-yehudi
    s2 = (mesh[1,1,0] - mesh[1,0,0])/(mesh[1,1,1]-mesh[1,0,1])
    o2 = mesh[1,0,0]

    # LE post-yehudi
    s3 = (mesh[0,2,0] - mesh[0,1,0])/(mesh[0,2,1]-mesh[0,1,1])
    o3 = mesh[0,2,0] - s3*mesh[0,2,1]

    # TE post-yehudi
    s4 = (mesh[1,2,0] - mesh[1,1,0])/(mesh[1,2,1]-mesh[1,1,1])
    o4 = mesh[1,2,0] - s4*mesh[1,2,1]

    n_points_total = n_points_inboard + n_points_outboard - 1
    half_mesh = np.zeros((2,n_points_total,3))

    # generate inboard points
    dy = (mesh[0,1,1] - mesh[0,0,1])/(n_points_inboard-1)
    for i in xrange(n_points_inboard):
        y = half_mesh[0,i,1] = i*dy
        half_mesh[0,i,0] = s1*y + o1 # le point
        half_mesh[1,i,1] = y
        half_mesh[1,i,0] = s2*y + o2 # te point

    yehudi_break = mesh[0,1,1]
    # generate outboard points
    dy = (mesh[0,2,1] - mesh[0,1,1])/(n_points_outboard-1)
    for j in xrange(n_points_outboard):
        i = j + n_points_inboard - 1
        y = half_mesh[0,i,1] = j*dy + yehudi_break
        half_mesh[0,i,0] = s3*y + o3 # le point
        half_mesh[1,i,1] = y
        half_mesh[1,i,0] = s4*y + o4 # te point

    full_mesh = mirror(half_mesh)
    return full_mesh


class GeometryMesh(Component):
    """ Changes a given mesh with span, sweep, and twist
    des-vars. Takes in a half mesh with symmetry plane about
    the middle and outputs a full symmetric mesh"""

    def __init__(self, mesh):
        super(GeometryMesh, self).__init__()

        self.mesh = mesh

        self.new_mesh = np.empty(mesh.shape, dtype=complex)
        self.new_mesh[:] = mesh
        n = self.mesh.shape[1]

        self.add_param('span', val=58.7630524)
        self.add_param('sweep', val=0.)
        self.add_param('twist', val=np.zeros(n))
        self.add_output('mesh', val=self.mesh)

        self.fd_options['force_fd']=True
        self.fd_options['form'] = 'complex_step'
        self.fd_options['extra_check_partials_form'] = "central"

    def solve_nonlinear(self, params, unknowns, resids):

        self.new_mesh[:] = self.mesh
        stretch(self.new_mesh, params['span'])
        sweep(self.new_mesh, params['sweep'])
        rotate(self.new_mesh, params['twist'])
        unknowns['mesh'] = self.new_mesh



class LinearInterp(Component):

    def __init__(self, num_y, name):
        super(LinearInterp, self).__init__()

        self.add_param('linear_'+name, val=np.zeros(2))
        self.add_output(name, val=np.zeros(num_y))

        self.fd_options['force_fd']=True
        self.fd_options['form'] = 'complex_step'
        self.fd_options['extra_check_partials_form'] = "central"

        self.num_y = num_y
        self.vname = name

    def solve_nonlinear(self, params, unknowns, resids):
        a, b = params['linear_'+self.vname]

        if self.num_y % 2 == 0:
            imax = int(self.num_y/2)
        else:
            imax = int((self.num_y+1)/2)
        for ind in xrange(imax):
            w = 1.0*ind/(imax-1)

            unknowns[self.vname][ind] = a*(1-w) + b*w
            unknowns[self.vname][-1-ind] = a*(1-w) + b*w



if __name__ == "__main__":
    import plotly.offline as plt
    import plotly.graph_objs as go

    from plot_tools import wire_mesh, build_layout

    thetas = np.zeros(20)
    thetas[10:] += 10

    mesh = mesh_gen(3,3)

    # new_mesh = rotate(mesh, thetas)

    # new_mesh = sweep(mesh, 20)

    new_mesh = stretch(mesh, 100)


    # wireframe_orig = wire_mesh(mesh)
    wireframe_new = wire_mesh(new_mesh)
    layout = build_layout()

    fig = go.Figure(data=wireframe_new, layout=layout)
    plt.plot(fig, filename="wing_3d.html")
