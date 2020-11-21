"""
Functions relating to the evaluation of the optical E-field by
summation of General Astigmatic Gaussian Beams
"""

from traits.api import on_trait_change, Float, Instance,Event, Int,\
        Property, Button, Str, Array

from traitsui.api import View, Item, VGroup, DropEditor

from tvtk.api import tvtk

from raytrace.bases import Probe, Traceable, NumEditor, Vector
from raytrace.sources import RayCollection, BaseRaySource

import numpy

from scipy.sparse.linalg import lsqr
from scipy.sparse import block_diag


def project_to_sphere(rays, phase, wavelengths, centre=(0,0,0), radius=10.0):
    """project the given set of rays back to their intercept 
    with a sphere at the given centre and radius.
    
    rays - an array of ray_t dtype
    phase - an array of phase values at the ray origins
    wavelengths - an array of wavelengths taken from the source
    """
    all_wavelengths = numpy.asarray(wavelengths)
    centre = numpy.asarray(centre).reshape(1,3)
    origin = rays['origin'] - centre
    direction = rays['direction'] #assume this is already normalised
    c = (origin**2).sum(axis=1) - (radius**2)
    b = 2*(direction * origin).sum(axis=1)
    a = 1 
    
    d = b**2 - 4*c
    selector = (d>=0.0)
    d = numpy.sqrt(d[selector])
    b = b[selector]
    root1 = (-b + d)/2
    root2 = (-b - d)/2
    #choose most negative path to intersection
    alpha = numpy.column_stack((root1, root2)).min(axis=1)
    
    rays = rays[selector]
    rays['origin'] += alpha[:,None]*direction[selector]
    
    wl = all_wavelengths[rays['wavelength_idx']]
    phase += (2000.0*numpy.pi)*alpha*rays['refractive_index'].real / wl
    return rays, phase 
    

def evaluate_neighbours(rays, neighbours_idx):
    """For each of a rays neighbours, we need to project the neighbour back
    onto the plane containing the main rays origin, to obtain the (x,y)
    cordinate for the neighbour ray, relative to the main ray origin
    
    rays - a ray_t array of length N
    neighbours_idx - a array on ints of shape (N,6)
    
    returns - a 5-tuple (rays, x,y,dx,dy) where x,y are N*6 arrays for the coordinate of each neighbour.
              dx and dy represent the change in direction of the neighbouring rays (i.e. 
              curvature of the wavefront). The returns rays are the subset of the input rays with
              6 neighbours (i.e. edge-rays are dropped).
              """
    
    mask = (neighbours_idx>=0).all(axis=1)
    nb = neighbours_idx[mask,:]
    n_origin = rays['origin'][nb,:]
    n_direction = rays['direction'][nb,:]
    origin = rays['origin'][mask,None,:]
    direction = rays['direction'][mask,None,:]
    E = rays['E_vector'][mask,None,:] #Assume normalised
    H = numpy.cross(E, direction) #Should also be unit length
    offsets = n_origin - origin
    alpha = -(offsets * direction).sum(axis=-1)/(n_direction * direction).sum(axis=-1)
    projected = (offsets + alpha[:,:,None]*n_direction)
    x = (projected * E).sum(axis=-1)
    y = (projected * H).sum(axis=-1)
    
    dz = (n_direction * direction).sum(axis=-1)
    dx = (n_direction * E).sum(axis=-1)/dz 
    dy = (n_direction * H).sum(axis=-1)/dz
    return (rays[mask], x,y,dx,dy)
    
    
def evaluate_modes(rays, neighbour_x, neighbour_y, dx, dy):
    """For each ray in rays, use its nearest neighbours
    to compute the best fit for the Astigmatic Gaussian Beam
    parameters.
    
    rays - an array of ray_t with shape (N,)
    x,y,dx,dy - array of shape (N,6)
    
    For N rays, return a Nx3 complex array of coeffs"""
    ### Do linear least squares on each ray and neighbours
    
    x = neighbour_x
    y = neighbour_y
    
    M = block_diag(numpy.dstack((x**2, 2*x*y, y**2)))
    b = numpy.ones(M.shape[0])
    fit = lsqr(M,b)
    im_coefs = fit[0].reshape(x.shape[0],3)

    O = numpy.zeros_like(x)
    upper = numpy.dstack((x,y,O))
    lower = numpy.dstack((O,x,y))
    combined = numpy.hstack((upper,lower))
    b = numpy.dstack( (dx,dy) ).reshape(-1)
    M = block_diag(combined)
    fit = lsqr(M,b)
    re_coefs = fit[0].reshape(x.shape[0],3)
    
    return (1j*im_coefs) + re_coefs
    
    
    
def evaluate_E(rays, mode_coeffs, points):
    """Evaluate the E-field at each position in the
    _points_ array.
    """
    
    
class EFieldPlane(Probe):    
    width = Float(0.5) #in mm
    size = Int(30)
            
    ray_source = Instance(klass="raytrace.sources.BaseRaySource")
    
    exit_pupil_offset = Float(10.0) #in mm
    
    ###The output of the probe
    E_field = Array()
    
    _eval_btn = Button("calculate")
    
    update = Event() #request re-tracing
    
    _plane_src = Instance(tvtk.PlaneSource, (), 
                    {"x_resolution":1, "y_resolution":1},
                    transient=True)
                    
    traits_view = View(VGroup(
                       Traceable.uigroup,
                       Item('size', editor=NumEditor),
                       Item('width', editor=NumEditor),
                        ),
                   )
    
        
    def __eval_btn_fired(self):
        source = self.ray_source
        
        pass
    
    @on_trait_change("size, width")
    def config_pipeline(self):
        src = self._plane_src
        size = self.size
        side = self.width/2.
        
        src.origin = (-side,-side,0)
        src.point1 = (-side,side,0)
        src.point2 = (side,-side,0)
        
        src.x_resolution = size
        src.y_resolution = size
        
        self.update = True
        
    @on_trait_change("centre, direction, orientation, exit_pupil_offset")
    def on_change(self):
        self.update = True
    
    def _actors_default(self):
        source = self._plane_src
        trans_f = tvtk.TransformFilter(input_connection=source.output_port,
                        transform = self.transform)
        map = tvtk.PolyDataMapper(input_connection=trans_f.output_port)
        act = tvtk.Actor(mapper=map)
        actors = tvtk.ActorCollection()
        actors.append(act)
        return actors
        
    def evaluate(self, ray_src):
        traced_rays = ray_src.TracedRays
        all_wavelengths = numpy.asarray(ray_src.wavelength_list)
        all_rays = [r.copy_as_array() for r in traced_rays]
        neighbours = ray_src.neighbour_list
        phases = ray_src.cumulative_phases
        
        intersections = [self.intersect_plane(rays) for rays in all_rays]
            
    def intersect_plane(self, rays):
        """
        @param rays: a numpy array of ray_t dtype
        
        intersect rays with plane, returning the indices of the intersecting rays
        """
        #raise NotImplementedError
        pass
    
    
    