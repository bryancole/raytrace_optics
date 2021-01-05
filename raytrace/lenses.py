#    Copyright 2009, Teraview Ltd., Bryan Cole
#
#    This file is part of Raytrace.
#
#    Raytrace is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

from traits.api import Float, Instance, on_trait_change, Array, Property,\
        cached_property, List, observe, Tuple

from traitsui.api import View, Item, ListEditor, VSplit,\
            RangeEditor, ScrubberEditor, HSplit, VGroup, Group, ListEditor

from tvtk.api import tvtk
     
from raytrace.bases import Optic, normaliseVector, NumEditor,\
    ComplexEditor, Traceable, transformPoints, transformNormals,\
    ShapedOptic
    
from raytrace.cfaces import CircularFace, SphericalFace, ConicRevolutionFace, AsphericFace
from raytrace.ctracer import FaceList
from raytrace.cmaterials import DielectricMaterial, CoatedDispersiveMaterial
from raytrace.shapes import CircleShape, BaseShape
from raytrace.vtk_algorithms import EmptyGridSource
from . import faces
from .materials import OpticalMaterial, air

import math, numpy
import itertools

def pairwise(itr):
    a1,a2 = itertools.tee(itr)
    next(a2)
    return zip(a1,a2)


class BaseLens(Optic):
    abstract = True


class PlanoConvexLens(BaseLens):
    abstract = False
    name = "Plano-Convex Lens"
    
    CT = Float(5.0, desc="centre thickness")
    diameter = Float(15.0)
    offset = Float(0.0)
    curvature = Float(11.7, desc="radius of curvature for spherical face")    
    
    vtk_grid = Instance(EmptyGridSource, ())
    vtk_cylinder = Instance(tvtk.Cylinder, ())
    vtk_sphere = Instance(tvtk.Sphere, ())
    
    clip2 = Instance(tvtk.ClipDataSet, ())
        
    traits_view = View(VGroup(
                       Traceable.uigroup,  
                       Item('n_inside'),
                       Item('CT', editor=NumEditor),
                       Item('diameter', editor=NumEditor),
                       Item('curvature', editor=NumEditor)
                       )
                    )
    
    def _faces_default(self):
        fl = FaceList(owner=self)
        fl.faces = [CircularFace(owner=self, diameter=self.diameter,
                                material = self.material), 
                SphericalFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                z_height=self.CT, curvature=self.curvature)]
        return fl
    
    def _CT_changed(self, new_ct):
        self.faces.faces[1].z_height = new_ct
        
    def _curvature_changed(self, new_curve):
        self.faces.faces[1].curvature = new_curve
    
    def make_step_shape(self):
        from .step_export import make_spherical_lens
        shape = make_spherical_lens(self.CT, self.diameter, self.curvature, 
                                   self.centre, self.direction, self.x_axis)
        return shape, "blue1"
    
    @on_trait_change("CT, diameter, curvature")
    def config_pipeline(self):
        ct = self.CT
        rad = self.diameter/2
        curve = self.curvature
        
        size = 41
        spacing = 2*rad / (size-1)
        if curve >= 0.0:
            extra=0.0
        else:
            extra = - curve - math.sqrt(curve**2 - rad**2)
        lsize = int((ct+extra)/spacing) + 2
        
        grid = self.vtk_grid
        grid.dimensions = (size,size,lsize)
        grid.origin = (-rad, -rad, 0)
        grid.spacing = (spacing, spacing, spacing)
                      
        cyl = self.vtk_cylinder
        cyl.center = (0,0,0)
        cyl.radius = rad
        
        s = self.vtk_sphere
        s.center = (0,0,ct - curve)
        s.radius = abs(curve)
        
        self.clip2.inside_out = bool(curve >= 0.0)
        
        self.vtk_grid.modified()
        self.update=True
        
                                         
    def _pipeline_default(self):
        grid = self.vtk_grid
        #grid.set_execute_method(self.create_grid)
        grid.modified()
        
        trans = tvtk.Transform()
        trans.rotate_x(90.)
        cyl = self.vtk_cylinder
        cyl.transform = trans
        
        clip1 = tvtk.ClipVolume(input_connection=grid.output_port,
                                 clip_function=self.vtk_cylinder,
                                 inside_out=1)
        
        self.clip2.set(input_connection = clip1.output_port,
                      clip_function=self.vtk_sphere,
                      inside_out=1)
        
        topoly = tvtk.GeometryFilter(input_connection=self.clip2.output_port)
        norms = tvtk.PolyDataNormals(input_connection=topoly.output_port)
        
        transF = tvtk.TransformFilter(input_connection=norms.output_port, 
                                      transform=self.transform)
        self.config_pipeline()
        grid.modified()
        return transF
    
    
class ShapedPlanoSphericLens(ShapedOptic):
    abstract = False
    name = "Plano-Convex Lens"
    
    CT = Float(5.0, desc="centre thickness")
    diameter = Float(15.0)
    offset = Float(0.0)
    curvature = Float(11.7, desc="radius of curvature for spherical face")
    
    shape = Instance(BaseShape, ())
    
    grid_extent = Property(depends_on="CT, diameter")
    
    traits_view = View(VGroup(
                       Traceable.uigroup,  
                       Item('n_inside'),
                       Item('CT', editor=NumEditor),
                       Item('diameter', editor=NumEditor),
                       Item('curvature', editor=NumEditor)
                       )
                    )
    
    def _shape_default(self):
        s1 = CircleShape(radius=self.diameter/2.)
        return s1
    
    def _faces_default(self):
        fl = FaceList(owner=self)
        fl.faces = [CircularFace(owner=self, diameter=self.diameter,
                                material = self.material), 
                SphericalFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                z_height=self.CT, curvature=self.curvature)]
        return fl
    
    @cached_property
    def _get_grid_extent(self):
        r = self.diameter/2
        return (-r,r,-r,r,0,self.CT)
    
    def _CT_changed(self, new_ct):
        self.faces.faces[1].z_height = new_ct
        self.update = True
        
    def _curvature_changed(self, new_curve):
        self.faces.faces[1].curvature = new_curve
        self.grid_in.modified()
        self.update = True
        
    def _diameter_changed(self, dnew):
        self.shape.radius = dnew/2.
        self.grid_in.modified()
        
    def eval_sag_top(self, points):
        centre = numpy.array([0,0,-(self.curvature-self.CT)])
        func = ((points - centre)**2).sum(axis=1) - (self.curvature**2)
        return func
    
    def eval_sag_bottom(self, points):
        return None
    
    
class SurfaceOfRotationLens(BaseLens):
    ###An array representing the 2D profile of the lens to be revolved
    profile = Array(shape=(None,2), dtype=numpy.double, transient=True)
    
    data_source = Instance(tvtk.ProgrammableSource, (), transient=True)
    
    revolve = Instance(tvtk.RotationalExtrusionFilter, (), 
                       {'capping': False,
                        'angle': 360.0,
                        'resolution': 60 
                        },
                        transient=True)
    
    def _pipeline_default(self):
        self.config_profile()
        
        source = self.data_source
        def execute():
            yz = self.profile
            x = numpy.zeros(yz.shape[0])
            points = numpy.column_stack((x,yz))
            
            cells = [list(range(len(x))),]
            
            output = source.poly_data_output
            output.points = points
            output.polys = cells
        source.set_execute_method(execute)
        print("Made PIPELINE")
        
        revolve = self.revolve
        revolve.input_connection = source.output_port
        
        t = self.transform
        transf = tvtk.TransformFilter(input_connection=revolve.output_port, 
                                      transform=t)
        return transf
    
    def _profile_changed(self):
        self.data_source.modified()
        self.faces.faces = self.make_faces()
        self.update=True
    
    def _faces_default(self):
        fl = FaceList(owner=self)
        fl.faces = self.make_faces()
        return fl
    
    def config_profile(self):
        pass
    
    def make_faces(self):
        return []
    
    
class PlanoConicLens(SurfaceOfRotationLens):
    abstract = False
    name = "Plano-Conic Section Lens"
    
    CT = Float(5.0, desc="centre thickness")
    diameter = Float(15.0)
    offset = Float(0.0) #Fixed at zero
    conic_const = Float(4.0, desc="conic constant")
    curvature = Float(11.7, desc="radius of curvature for spherical face")
    
    traits_view = View(VGroup(
                       Traceable.uigroup,  
                       Item('n_inside'),
                       Item('CT', editor=NumEditor),
                       Item('diameter', editor=NumEditor),
                       Item('curvature', editor=NumEditor),
                       Item('conic_const', editor=NumEditor)
                       )
                    )
    
    def make_faces(self):
        fl = [CircularFace(owner=self, diameter=self.diameter,
                                material = self.material), 
                ConicRevolutionFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                conic_const=self.conic_const,
                                z_height=self.CT, curvature=self.curvature)]
        return fl
    
    def _CT_changed(self, new_ct):
        self.faces.faces[1].z_height = new_ct
        
    def _curvature_changed(self, new_curve):
        self.faces.faces[1].curvature = new_curve
        
    def _conic_const_changed(self, new_conic):
        self.faces.faces[1].conic_const = new_conic
        
    @on_trait_change("CT, diameter, conic_const, curvature")
    def config_profile(self):
        n_segments = 20 #number of lines in the curved section
        r_max = self.diameter/2 #maximum radius
        k = self.conic_const
        R = self.curvature
        r = numpy.linspace(0,r_max, n_segments)
        
        z = self.CT - (r**2)/(R*(1 + numpy.sqrt(1 - (1+k)*(r**2)/(R**2))))
        
        profile = list(zip(r,z))
        profile.extend([(r_max, 0.0), (0.0,0.0)])
        self.profile = profile
        
    
    
    
class BiConicLens(PlanoConicLens):
    name = "Bi-Conic Section Lens"
    
    conic_const2 = Float(-4.0, desc="conic constant, lower face")
    curvature2 = Float(11.7, desc="radius of curvature for spherical face")
    
    traits_view = View(VGroup(
                       Traceable.uigroup,  
                       Item('n_inside'),
                       Item('CT', editor=NumEditor),
                       Item('diameter', editor=NumEditor),
                       Item('curvature', editor=NumEditor),
                       Item('conic_const', editor=NumEditor),
                       Item('curvature2', editor=NumEditor),
                       Item('conic_const2', editor=NumEditor)
                       )
                    )
    
    def _curvature2_changed(self, new_curve):
        self.faces.faces[0].curvature = new_curve
        
    def _conic_const2_changed(self, new_conic):
        self.faces.faces[0].conic_const = new_conic
    
    def make_faces(self):
        fl = [ConicRevolutionFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                conic_const=self.conic_const2,
                                z_height=0.0, curvature=self.curvature2,
                                invert_normals=True), 
                ConicRevolutionFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                conic_const=self.conic_const,
                                z_height=self.CT, curvature=self.curvature)]
        return fl

    @on_trait_change("CT, diameter, conic_const, curvature, conic_const2, curvature2")
    def config_profile(self):
        n_segments = 20 #number of lines in the curved section
        r_max = self.diameter/2 #maximum radius
        k = self.conic_const
        k2 = self.conic_const2
        R = self.curvature
        R2 = self.curvature2
        r = numpy.linspace(0,r_max, n_segments)
        
        #top surface
        z = self.CT - (r**2)/(R*(1 + numpy.sqrt(1 - (1+k)*(r**2)/(R**2))))
        z2 = - (r**2)/(R2*(1 + numpy.sqrt(1 - (1+k2)*(r**2)/(R2**2))))
        
        profile = list(zip(r,z))
        profile2 = list(zip(r,z2))
        
        profile.extend(profile2[-1::-1])
        self.profile = profile
        
        
class AsphericLens(SurfaceOfRotationLens):
    abstract = False
    name = "Bi-Aspheric Lens"
    
    CT = Float(5.0, desc="centre thickness")
    diameter = Float(25.0)
    offset = Float(0.0) #Fixed at zero
    
    A_curvature = Float(-25.0)
    A_conic = Float(-0.0)
    A4 = Float(0.0)
    A6 = Float(0.0)
    A8 = Float(0.0)
    A10 = Float(0.0)
    A12 = Float(0.0)
    A14 = Float(0.0)
    A16 = Float(0.0)
    
    B_curvature = Float(25.0)
    B_conic = Float(-0.0)
    B4 = Float(0.0)
    B6 = Float(0.0)
    B8 = Float(0.0)
    B10 = Float(0.0)
    B12 = Float(0.0)
    B14 = Float(0.0)
    B16 = Float(0.0)
    
    traits_view = View(VGroup(
                       Traceable.uigroup,  
                       Item('n_inside'),
                       Item('CT', editor=NumEditor),
                       Item('diameter', editor=NumEditor),
                       VGroup(
                           Item('A_curvature', editor=NumEditor),
                           Item('A_conic', editor=NumEditor),
                           Item('A4', editor=NumEditor),
                           Item('A6', editor=NumEditor),
                           Item('A8', editor=NumEditor),
                           Item('A10', editor=NumEditor),
                           label="A Surface",
                           show_border = True
                           ),
                       VGroup(
                           Item('B_curvature', editor=NumEditor),
                           Item('B_conic', editor=NumEditor),
                           Item('B4', editor=NumEditor),
                           Item('B6', editor=NumEditor),
                           Item('B8', editor=NumEditor),
                           Item('B10', editor=NumEditor),
                           label="B Surface",
                           show_border = True
                           ),
                       )
                    )
    
#     def make_faces(self):
#         fl = [ConicRevolutionFace(owner=self, diameter=self.diameter,
#                                 material=self.material,
#                                 conic_const=self.A_conic,
#                                 z_height=0.0, curvature=self.A_curvature,
#                                 invert_normals=True), 
#                 ConicRevolutionFace(owner=self, diameter=self.diameter,
#                                 material=self.material,
#                                 conic_const=self.B_conic,
#                                 z_height=self.CT, curvature=self.B_curvature)]
#         return fl
    
    def make_faces(self):
        fl = [AsphericFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                conic_const=self.A_conic,
                                z_height=0.0, curvature=self.A_curvature,
                                A4=-self.A4, A6=-self.A6, A8=-self.A8, A10=-self.A10,
                                A12=-self.A12, A14=-self.A14, A16=-self.A16,
                                invert_normals=True,
                                atol=1e-16), 
                AsphericFace(owner=self, diameter=self.diameter,
                                material=self.material,
                                conic_const=self.B_conic,
                                z_height=self.CT, curvature=self.B_curvature,
                                A4=-self.B4, A6=-self.B6, A8=-self.B8, A10=-self.B10,
                                A12=-self.B12, A14=-self.B14, A16=-self.B16,
                                atol=1e-16)]
        return fl
    
    def eval_A(self, y):
        y2=numpy.asarray(y)**2
        R = self.A_curvature
        beta = (1 + self.A_conic)
        z = self.A4*(y2**2) + self.A6*(y2**3) + self.A8*(y2**4) + self.A10*(y2**5) + y2 / (R*(1 + numpy.sqrt(1 - beta*y2/(R**2))))
        return -z
    
    def eval_B(self, y):
        y2=numpy.asarray(y)**2
        R = self.B_curvature
        beta = (1 + self.B_conic)
        z = self.B4*(y2**2) + self.B6*(y2**3) + self.B8*(y2**4) + self.B10*(y2**5) + y2 / (R*(1 + numpy.sqrt(1 - beta*y2/(R**2))))
        return self.CT - z
    
    @on_trait_change("CT, diameter, A_conic, A_curvature, A4, A6, A8, A10, B_conic, B_curvature, B4, B6, B8, B10")
    def config_profile(self):
        n_segments = 20 #number of lines in the curved section
        r_max = self.diameter/2 #maximum radius
        r = numpy.linspace(0,r_max, n_segments)
        
        profile = list(zip(r, self.eval_A(r)))
        profile2 = list(zip(r, self.eval_B(r)))
        
        profile.extend(profile2[-1::-1])
        self.profile = profile
    
    
alist_editor = ListEditor(use_notebook=True,
                           deletable=False,
                           selected='selected',
                           export='DockWindowShell',
                           page_name='.name')
    
    
class GeneralLens(ShapedOptic):
    shape = Instance(BaseShape)
    
    surfaces = List(faces.PlanarFace)
    
    materials = List(OpticalMaterial)
    
    _grids = List()
    
    coating_material = Instance(OpticalMaterial, ())
    coating_thickness = Float(0.25, desc="Thickness of the AR coating, in microns")
    
    grid_resolution = Tuple((200,200,30))
    
    traits_view = View(Group(
                Traceable.uigroup,
                Group(
                    Item("shape", show_label=False, style="custom"),
                    label="Outline", dock="tab"
                    ),
                Group(
                    Item("surfaces", style="custom",
                         editor=alist_editor, 
                         show_label=False),
                    label="Faces", dock="tab"
                    ),
                Group(
                    VGroup(
                    Item("materials", style="custom", editor=alist_editor, show_label=False),
                    ),
                    Item("coating_material", style="custom"),
                    Item("coating_thickness", editor=NumEditor),
                    label="Materials", dock="tab"
                    ),
                layout="tabbed"
            )
        )
    
    
    def _pipeline_default(self):
        nx,ny,nz = self.grid_resolution
        xmin,xmax,ymin,ymax,zmin,zmax = self.grid_extent
        
        shape = self.shape
        func = shape.impl_func
        
        _grids = []
        
        append = tvtk.AppendPolyData()
        
        grid = tvtk.PlaneSource(origin=(xmin,ymin,0),
                                point1=(xmin,ymax,0),
                                point2=(xmax,ymin,0),
                                x_resolution=nx,
                                y_resolution=ny)
    
        clip = tvtk.ClipPolyData(input_connection=grid.output_port,
                                     inside_out=1)
        clip.clip_function = func
        
        for face in self.surfaces:
            attrb = tvtk.ProgrammableAttributeDataFilter(input_connection=clip.output_port)
            
            ###Beware, references to outer scope change in the loop. Capture state using kwd-args.
            def execute( *args , _face=face, _attrb=attrb):
                in_data = _attrb.get_input_data_object(0,0)
                points = in_data.points.to_array()
                z = _face.cface.eval_z_points(points.astype('d'))
                out = _attrb.get_output_data_object(0)
                out.point_data.scalars=z

            attrb.set_execute_method(execute)
            
            warp = tvtk.WarpScalar(input_connection=attrb.output_port,scale_factor=1.0)
            warp.normal=(0,0,1)
            warp.use_normal=True
            
            append.add_input_connection(warp.output_port)
        
        _grids.append( (grid,clip) )
        
        transF = tvtk.TransformFilter(input_connection=append.output_port, 
                                      transform=self.transform)
        self._grids = _grids
        return transF
            
    
    def _faces_default(self):
        fl = FaceList(owner=self)
        fl.faces = [f.cface for f in self.surfaces]
        for face in fl.faces:
            face.owner=self
        return fl
    
    @observe("materials.items.dispersion_curve")
    def on_material_change(self, evt):
        if evt.object is self:
            if len(evt.new) + 1 != len(self.surfaces):
                return
            self.surfaces[0].cface.material.dispersion_outside = air
            self.surfaces[1].cface.material.dispersion_inside = air
            for (f1,f2),item in zip(pairwise(self.surfaces),evt.new):
                f1.cface.material.dispersion_inside = item.dispersion_curve
                f2.cface.material.dispersion_outside = item.dispersion_curve
        else:
            idx = self.materials.index(evt.object)
            f1,f2 = self.surfaces[idx:idx+2]
            f1.cface.material.dispersion_inside = evt.new
            f2.cface.material.dispersion_outside = evt.new
        
    @observe("surfaces.items.updated")
    def on_surfaces_changed(self, evt):
        if evt.object is self:
            for item in evt.new:
                item.cface.shape = self.shape.cshape
                item.cface.material = CoatedDispersiveMaterial()
        else:
            print(evt)
            evt.object.cface.shape = self.shape.cshape
            evt.object.cface.material = CoatedDispersiveMaterial()
        self.on_bounds_change(None)

    @observe("shape.impl_func, surfaces")
    def on_impl_func_change(self, evt):
        self.clip.clip_function = self.shape.impl_func
        for g in self._grids:
            g[1].clip_function = self.shape.impl_func
        self.render=True
            
    @observe("shape.updated")
    def on_shape_updated(self, evt):
        for face in self.surfaces:
            face.cface.shape = self.shape.cshape
        self.update=True
    
    @observe("shape.bounds, surfaces")
    def on_bounds_change(self, evt):
        nx, ny, nz = self.grid_resolution
        xmin, xmax, ymin, ymax = self.shape.bounds
        zmin, zmax = self.eval_z_extent(xmin, xmax, ymin, ymax)
        self.grid_extent = (xmin, xmax, ymin, ymax, zmin, zmax)
        for g,c in self._grids:
            g.origin=(xmin,ymin,0)
            g.point1=(xmin,ymax,0)
            g.point2=(xmax,ymin,0)
            g.x_resolution=nx
            g.y_resolution=ny
            g.modified()
    
    def eval_z_extent(self, xmin, xmax, ymin, ymax):
        nx, ny, nz = self.grid_resolution
        try:
            top_face = self.surfaces[0]
            bottom_face = self.surfaces[-1]
        except IndexError:
            return 0,0
        x = numpy.linspace(xmin, xmax, nx)
        y = numpy.linspace(ymin, ymax, ny)
        tzmin, tzmax = top_face.cface.eval_z_extent(x,y)
        bzmin, bzmax = bottom_face.cface.eval_z_extent(x,y)
        return ( min(tzmin,bzmin), max(tzmax, bzmax) )
    
    def eval_sag_top(self, points):
        top_face = self.surfaces[0]
        z_top = top_face.cface.eval_implicit_points(points.astype('d'))
        return z_top 
    
    def eval_sag_bottom(self, points):
        bottom_face = self.surfaces[-1]
        z_bottom = bottom_face.cface.eval_implicit_points(points.astype('d'))
        return z_bottom 

        
if __name__=="__main__":
    from raytrace.tracer import RayTraceModel
    from raytrace.sources import ConfocalRaySource
    
    lens = PlanoConvexLens(orientation=0.0,
                           elevation=0.0,
                           CT=5.,
                           curvature=12.)
    
    source = ConfocalRaySource(focus=(0,0,-30),
                            direction=(0,0,1),
                            working_dist = 0.1,
                            number=20,
                            detail_resolution=5,
                            theta=10.,
                            scale_factor=0.1)
    
    model = RayTraceModel(optics=[lens], 
                          sources=[source,])
    model.configure_traits()
