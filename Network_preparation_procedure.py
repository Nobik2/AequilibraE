"""
/***************************************************************************
 AequilibraE - www.aequilibrae.com
 
    Name:        Main interface for modeling tools
                              -------------------
        begin                : 2014-03-19
        copyright            : AequilibraE developers 2014
        Original Author: Pedro Camargo pedro@xl-optim.com
        Contributors: 
        Licence: See LICENSE.TXT
 ***************************************************************************/
"""

from qgis.core import *
from PyQt4.QtCore import *
import numpy as np
from auxiliary_functions import *
from WorkerThread import WorkerThread
from global_parameters import *

class FindsNodes(WorkerThread):
    def __init__(self, parentThread, line_layer, new_line_layer, node_layer=False, node_ids=False, new_node_layer=False, node_start = 0):
        WorkerThread.__init__(self, parentThread)
        self.line_layer = line_layer
        self.node_layer = node_layer
        self.node_ids = node_ids
        self.new_node_layer = new_node_layer
        self.new_line_layer = new_line_layer
        self.node_start = node_start
        self.error = None

    def doWork(self):
        line_layer = self.line_layer
        node_layer = self.node_layer
        node_ids = self.node_ids
        layer = getVectorLayerByName(line_layer)
        featcount = layer.featureCount()
        self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), featcount)

        P = 0
        for feature in layer.getFeatures():
            P += 1
            self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Detecting if layer is Singleparts: " + str(P) + "/" + str(featcount))
            geom = feature.geometry()
            if geom.isMultipart():
               self.error = 'Layer is Multipart. Please go to "Vector-Geometry Tools-Multipart to Singleparts..."'
               return None

        self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), 3)
        self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), 0)
        self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Duplicating line layer")

        P = 0
        # We create the new line layer and load it in memory
        EPSG_code = int(layer.crs().authid().split(":")[1])
        new_line_layer = QgsVectorLayer(layer.source(), layer.name(), layer.providerType())
        QgsVectorFileWriter.writeAsVectorFormat(new_line_layer, self.new_line_layer, str(EPSG_code), None, "ESRI Shapefile")
        self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), 1)

        new_line_layer = QgsVectorLayer(self.new_line_layer, 'noded_layer', 'ogr')

        # Add the A_Node and B_node fields to the layer
        field_names = [x.name().upper() for x in new_line_layer.dataProvider().fields().toList()]
        add_fields = ['A_NODE', 'B_NODE']
        for f in add_fields:
            if f not in field_names:
                res = new_line_layer.dataProvider().addAttributes([QgsField(f, QVariant.Int)])
        new_line_layer.updateFields()
        self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), 2)
        # I f we have node IDs, we iterate over the ID field to make sure they are unique
        ids = []
        if node_ids != False:
            nodes = getVectorLayerByName(node_layer)
            index = QgsSpatialIndex()
            idx = nodes.fieldNameIndex(node_ids)

            self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), nodes.featureCount())
            self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), 0)

            for P, feat in enumerate(nodes.getFeatures()):
                self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Checking node layer: " + str(P) + "/" + str(nodes.featureCount()))
                self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), P)
                index.insertFeature(feat)
                i_d = feat.attributes()[idx]
                if i_d in ids:
                    self.error = "ID " + str(i_d) + ' is non unique in your selected field'
                    return None
                if i_d < 0:
                    self.error = "Negative node ID in your selected field"
                    return None
                ids.append(i_d)

            P = 0
            for feat in new_line_layer.getFeatures():
                P += 1
                self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
                self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Links Analyzed: " + str(P) + "/" + str(featcount))

                # We search for matches for all AB nodes
                ab_nodes=[('A_NODE', 0), ('B_NODE', -1)]
                for field, position in ab_nodes:
                    node_ab = list(feat.geometry().asPolyline())[position]

                    # We compute the closest node
                    nearest = index.nearestNeighbor(QgsPoint(node_ab), 1)

                    # We get coordinates on this node
                    fid = nearest[0]
                    nfeat = nodes.getFeatures(QgsFeatureRequest(fid)).next()
                    nf = nfeat.geometry().asPoint()

                    fid = new_line_layer.fieldNameIndex(field)
                    # We see if they are really the same node
                    if round(nf[0],10) == round(node_ab[0], 10) and round(nf[1], 10) == round(node_ab[1], 10):
                        ids = nfeat.attributes()[idx]
                        new_line_layer.dataProvider().changeAttributeValues({feat.id(): {fid: int(ids)}})

                    else: # If not, we throw an error
                        new_line_layer.dataProvider().changeAttributeValues({feat.id(): {fid: -10000}})
                        self.error = 'CORRESPONDING NODE NOTE FOUND'
                        return None

                new_line_layer.commitChanges()
        else:
            #  Create node layer
            new_node_layer = QgsVectorLayer('Point?crs=epsg:' + str(EPSG_code) + '&field=ID:integer', "temp", "memory")
            DTYPE = [('LAT', np.float64), ('LONG', np.float64), ('LINK ID', np.int64), ('POSITION', np.int64), ('NODE ID', np.int64)]
            all_nodes = np.zeros(featcount * 2, dtype=DTYPE)

            l = 0
            #  Let's read all links and the coordinates for their extremities
            for feat in new_line_layer.getFeatures():
                P += 1
                if P % 500 == 0:
                    self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
                    self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Links read: " + str(P) + "/" + str(featcount))

                link = list(feat.geometry().asPolyline())

                node_a = (round(link[0][0], 10), round(link[0][1], 10))
                node_b = (round(link[-1][0], 10), round(link[-1][1], 10))

                link_id = feat.id()

                all_nodes[l][0] = node_a[0]
                all_nodes[l][1] = node_a[1]
                all_nodes[l][2] = link_id
                all_nodes[l][3] = 0
                l += 1
                all_nodes[l][0] = node_b[0]
                all_nodes[l][1] = node_b[1]
                all_nodes[l][2] = link_id
                all_nodes[l][3] = 1
                l += 1

            # Now we sort the nodes and assign IDs to them
            all_nodes = np.sort(all_nodes, order=['LAT', 'LONG'])

            lat0 = -100000.0
            longit0 = -100000.0
            incremental_ids = self.node_start - 1
            P = 0

            self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), featcount * 2)
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Computing node IDs: " + str(0)+"/" + str(featcount * 2))
            self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), featcount * 2)

            for i in all_nodes:
                P += 1
                lat, longit, link_id, position, node_id = i

                if lat != lat0 or longit != longit0:
                    incremental_ids += 1
                    lat0 = lat
                    longit0 = longit

                i[4] = incremental_ids

                if P % 2000 == 0:
                    self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
                    self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Computing node IDs: " + str(P) + "/" + str(featcount * 2))

            self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(featcount * 2))
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Computing node IDs: " + str(featcount * 2)+"/" + str(featcount * 2))

            # And we write the node layer as well
            node_id0 = -1
            P=0
            self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), incremental_ids)
            cfeatures = []
            for i in all_nodes:
                lat, longit, link_id, position, node_id = i

                if node_id != node_id0:
                    P += 1
                    feature = QgsFeature()
                    feature.setGeometry(QgsGeometry.fromPoint(QgsPoint(lat, longit)))
                    feature.setAttributes([int(node_id)])
                    cfeatures.append(feature)
#                    new_node_layer.dataProvider().addFeatures([feature])
                    node_id0 = node_id

                if P % 500 == 0:
                    self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
                    self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Writing new node layer: " + str(P) + "/" + str(incremental_ids))

            a = new_node_layer.dataProvider().addFeatures(cfeatures)
            del cfeatures
            new_node_layer.commitChanges()
            self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(incremental_ids))
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Writing new node layer: " + str(incremental_ids) + "/" + str(incremental_ids))

            # Now we write all the node _IDs back to the line layer
            P = 0
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Writing node IDs to links: " + str(0) + "/" + str(featcount * 2))
            self.emit(SIGNAL("ProgressMaxValue(PyQt_PyObject)"), featcount * 2)
            fid1 = new_line_layer.fieldNameIndex("A_NODE")
            fid2 = new_line_layer.fieldNameIndex("B_NODE")
            for i in all_nodes:
                P += 1
                lat, longit, link_id, position, node_id = i

                if position == 0:
                    new_line_layer.dataProvider().changeAttributeValues({int(link_id): {fid1: int(node_id)}})
                else:
                    new_line_layer.dataProvider().changeAttributeValues({int(link_id): {fid2: int(node_id)}})

                if P % 50 == 0:
                    self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
                    self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Writing node IDs to links: " + str(P) + "/" + str(featcount * 2))

            self.emit(SIGNAL("ProgressValue(PyQt_PyObject)"), int(P))
            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "Writing node IDs to links: " + str(P)+"/" + str(featcount * 2))

            self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "SAVING OUTPUTS")

            QgsVectorFileWriter.writeAsVectorFormat(new_node_layer, self.new_node_layer, "utf-8", None, "ESRI Shapefile")

            new_line_layer.commitChanges()
            QgsMapLayerRegistry.instance().addMapLayer(new_line_layer)

        self.emit(SIGNAL("ProgressText (PyQt_PyObject)"), "DONE")