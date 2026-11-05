import networkx as nx
from datetime import datetime, timedelta
from database import Transaction
from db import db
import logging

logger = logging.getLogger(__name__)

class TransactionGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.last_built = None
        self.cache_duration = timedelta(minutes=30)

    def build_from_db(self):
        """
        Queries transactions from the last 30 days and rebuilds the NetworkX
        directed graph representation of payment flows.
        """
        # Re-build graph only if cache has expired
        now = datetime.utcnow()
        if (self.last_built and (now - self.last_built) < self.cache_duration):
            return

        logger.info("🕸️ Rebuilding NetworkX transaction social graph from database...")
        # Build into a fresh graph and swap at the end: clearing self.graph in place let
        # concurrent request threads see an empty graph mid-rebuild.
        graph = nx.DiGraph()
        
        try:
            thirty_days_ago = now - timedelta(days=30)
            # Query all transaction edges from last 30 days
            txns = Transaction.query.filter(Transaction.created_at >= thirty_days_ago)\
                                    .filter(Transaction.status.in_(['APPROVED', 'APPROVED_WITH_WARNING', 'COMPLETED']))\
                                    .all()
                                    
            from security import decrypt_val
            for txn in txns:
                # Add edge with transaction weight (amount)
                sender = decrypt_val(txn.sender_upi)
                receiver = decrypt_val(txn.receiver_upi)
                amount = float(txn.amount)
                
                if graph.has_edge(sender, receiver):
                    graph[sender][receiver]['weight'] += amount
                    graph[sender][receiver]['count'] += 1
                else:
                    graph.add_edge(sender, receiver, weight=amount, count=1)
                    
            self.graph = graph
            self.last_built = now
            logger.info(f"✅ Social Graph built: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")
        except Exception as e:
            logger.error(f"Failed to build transaction social graph: {e}")

    def is_mule_candidate(self, upi_id: str) -> tuple:
        """
        Check if a given UPI ID matches known money mule topological signatures:
        - Signature 1: > 50 unique incoming senders and < 5 unique outgoing receivers (Score: 80)
        - Signature 2: > 20 unique incoming senders and exactly 1 outgoing receiver (Score: 90)
        Returns: (is_mule: bool, risk_score: int)
        """
        self.build_from_db()
        
        if upi_id not in self.graph:
            return False, 0
            
        in_degree = self.graph.in_degree(upi_id)   # Unique incoming senders
        out_degree = self.graph.out_degree(upi_id) # Unique outgoing receivers
        
        # Check money mule topologies
        if in_degree > 50 and out_degree < 5:
            logger.warning(f"🚨 Mule Topology Match (50+ in, <5 out): node {upi_id}")
            return True, 80
        elif in_degree > 20 and out_degree == 1:
            logger.warning(f"🚨 Mule Topology Match (20+ in, 1 out): node {upi_id}")
            return True, 90
            
        return False, 0

    def get_centrality_score(self, upi_id: str) -> float:
        """
        Calculates the degree centrality of a UPI ID within the network.
        Nodes with high centrality represent critical routing points.
        """
        self.build_from_db()
        if upi_id not in self.graph:
            return 0.0
            
        try:
            # We use degree centrality as betweenness can be expensive for large networks
            # and degree centrality is robust for local node traffic
            # Same value as nx.degree_centrality(G)[node] without scoring every node per request.
            n = self.graph.number_of_nodes()
            return float(self.graph.degree(upi_id)) / (n - 1) if n > 1 else 0.0
        except Exception as e:
            logger.error(f"Failed to calculate centrality score: {e}")
            return 0.0

# Singleton global instance of the transaction graph
global_txn_graph = TransactionGraph()
