import { useState, useEffect } from 'react';
import { 
  LayoutDashboard, AlertTriangle, Activity, Bed, 
  ShieldCheck, UserCheck, FileText, Settings,
  Search, Bell, User, CheckCircle2, BrainCircuit, ArrowLeft, Loader2,
  Stethoscope, Wrench, Clock
} from 'lucide-react';
import { fetchState, approveProposal } from './api';

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  
  // API State
  const [stateData, setStateData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(false);

  // New Incident State
  const [incidentText, setIncidentText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<any>(null);

  // Human Review State
  const activeProposal = {
    id: "INC-TEST-01",
    incident: "Emergency in Ward 4. Two incoming patients with severe chest pain.",
    triage: "P1 (Critical)",
    aiSummary: "High risk of cardiac event. Patient requires immediate ICU bed, critical care doctor, emergency nurse, and ventilator support.",
    resources: [
      { type: 'Bed', id: 'B-H01-ICU-01', status: 'Available' },
      { type: 'Doctor', id: 'D02', status: 'Available' },
      { type: 'Nurse', id: 'N01', status: 'Available' },
      { type: 'Equipment', id: 'VENT-H01-01', status: 'Available' }
    ],
    validationStatus: "PASS"
  };

    useEffect(() => {
    // Add a timeout so the UI doesn't spin forever if the API is down
    const timeout = setTimeout(() => setLoading(false), 2000);

    fetchState()
      .then(data => {
        setStateData(data);
        setLoading(false);
        setApiError(false);
        clearTimeout(timeout);
      })
      .catch(err => {
        console.error("API Error:", err);
        setApiError(true);
        setLoading(false);
        clearTimeout(timeout);
      });

    return () => clearTimeout(timeout);
  }, [activeTab]);

  const freeBeds = stateData?.beds?.filter((b: any) => b.status === 'free').length || 0;
  const totalBeds = stateData?.beds?.length || 0;
  const availableNurses = stateData?.nurses?.filter((n: any) => n.available).length || 0;
  const totalNurses = stateData?.nurses?.length || 0;

  const handleSubmitIncident = async () => {
    if (!incidentText.trim()) return;
    setIsSubmitting(true);
    setSubmitResult(null);

    try {
      const response = await fetch('http://127.0.0.1:8000/incidents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          incident_id: `INC-${Date.now()}`,
          patient_id: "PT-001",
          hospital_id: "H01",
          reported_severity: "critical",
          description: incidentText
        })
      });

      const data = await response.json();
      setSubmitResult(data);
    } catch (error) {
      console.error(error);
      setSubmitResult({ error: "Failed to connect to backend API. Is Uvicorn running?" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const renderContent = () => {
    if (activeTab === 'overview') {
      return (
        <div className="space-y-8">
          <div className="flex justify-between items-end">
            <div>
              <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Hospital Command Center</h1>
              <p className="text-slate-500 mt-1 font-medium">Real-time status across all connected facilities.</p>
            </div>
            {apiError ? (
              <span className="bg-rose-100 text-rose-800 text-xs font-bold px-3 py-1 rounded-full border border-rose-200">API OFFLINE</span>
            ) : (
              <span className="bg-emerald-100 text-emerald-800 text-xs font-bold px-3 py-1 rounded-full border border-emerald-200">LIVE DATA</span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <StatCard title="Available Beds" value={loading ? "..." : freeBeds.toString()} total={loading ? "" : totalBeds.toString()} icon={<Bed size={24} />} color="text-blue-600" bg="bg-blue-50" />
            <StatCard title="Active Incidents" value="2" total="" icon={<AlertTriangle size={24} />} color="text-rose-600" bg="bg-rose-50" />
            <StatCard title="Pending Reviews" value="1" total="" icon={<UserCheck size={24} />} color="text-purple-600" bg="bg-purple-50" />
            <StatCard title="Available Nurses" value={loading ? "..." : availableNurses.toString()} total={loading ? "" : totalNurses.toString()} icon={<Activity size={24} />} color="text-emerald-600" bg="bg-emerald-50" />
          </div>

          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-5 border-b border-slate-200 flex justify-between items-center bg-slate-50">
              <h2 className="text-lg font-bold text-slate-800">Live Incident Board</h2>
            </div>
            <table className="w-full text-left">
              <thead className="bg-white border-b border-slate-200 text-slate-400 text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-4 font-bold">Time</th>
                  <th className="px-6 py-4 font-bold">Incident ID</th>
                  <th className="px-6 py-4 font-bold">Location</th>
                  <th className="px-6 py-4 font-bold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-6 py-4 text-sm font-medium text-slate-600">Just now</td>
                  <td className="px-6 py-4 text-sm font-bold text-slate-800">INC-TEST-01</td>
                  <td className="px-6 py-4 text-sm text-slate-600">Ward 4</td>
                  <td className="px-6 py-4"><span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-xs font-bold">Pending Review</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    if (activeTab === 'incident') {
      return (
        <div className="space-y-6">
          <h1 className="text-2xl font-extrabold text-slate-900">Report New Incident</h1>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-6">
            <label className="block text-sm font-bold text-slate-700 mb-2">Incident Description</label>
            <textarea 
              value={incidentText}
              onChange={(e) => setIncidentText(e.target.value)}
              className="w-full border border-slate-300 rounded-lg p-4 text-sm focus:ring-2 focus:ring-blue-500 outline-none h-32 resize-none"
              placeholder="e.g., An emergency has been reported in Ward 4. Two incoming patients with severe chest pain."
            ></textarea>
            <button 
              onClick={handleSubmitIncident}
              disabled={isSubmitting || !incidentText.trim()}
              className="mt-4 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white font-bold py-3 px-6 rounded-xl transition-all flex items-center gap-2"
            >
              {isSubmitting ? <Loader2 className="animate-spin" size={20} /> : <BrainCircuit size={20} />}
              {isSubmitting ? "AI is analyzing..." : "Submit to AI Pipeline"}
            </button>

            {submitResult && (
              <div className={`mt-6 p-4 rounded-lg border text-sm font-medium ${submitResult.error ? 'bg-rose-50 border-rose-200 text-rose-800' : 'bg-emerald-50 border-emerald-200 text-emerald-800'}`}>
                {submitResult.error ? (
                  <p>{submitResult.error}</p>
                ) : (
                  <div>
                    <p className="font-bold mb-1">✅ Incident Saved & AI Pipeline Started</p>
                    <p>Incident ID: {submitResult.incident_id}</p>
                    <p>Status: {submitResult.status} (Check the Human Review tab shortly)</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      );
    }

    if (activeTab === 'review') {
      return (
        <div className="space-y-6">
          <div className="flex items-center gap-4 mb-2">
            <button className="p-2 hover:bg-slate-200 rounded-full transition-colors"><ArrowLeft size={20} className="text-slate-600"/></button>
            <div>
              <h1 className="text-2xl font-extrabold text-slate-900 flex items-center gap-3">
                Incident {activeProposal.id}
                <span className="bg-blue-100 text-blue-700 text-xs font-bold px-3 py-1 rounded-full">AI Analysis</span>
              </h1>
              <p className="text-slate-500 font-medium mt-1">{activeProposal.incident}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="xl:col-span-1 space-y-6">
              <div className="bg-white border border-blue-200 rounded-2xl shadow-sm overflow-hidden h-full flex flex-col">
                <div className="bg-blue-50 px-6 py-4 border-b border-blue-200 flex justify-between items-center">
                  <h2 className="font-bold text-blue-900 flex items-center gap-2"><BrainCircuit size={18}/> AI Proposed Solution</h2>
                </div>
                <div className="p-6 space-y-6 flex-1">
                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Triage Assessment</h3>
                    <p className="text-sm font-bold text-rose-600 bg-rose-50 p-2 rounded border border-rose-100">{activeProposal.triage}</p>
                  </div>
                  <div>
                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Resource Assignments</h3>
                    <div className="space-y-2">
                      {activeProposal.resources.map((r, i) => (
                        <div key={i} className="bg-slate-50 border border-slate-100 rounded-lg p-3 flex justify-between items-center">
                          <div>
                            <p className="text-xs font-bold text-slate-400 uppercase">{r.type}</p>
                            <p className="text-sm font-bold text-slate-800">{r.id}</p>
                          </div>
                          <span className="text-xs font-bold text-emerald-600 bg-emerald-100 px-2 py-1 rounded">{r.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="xl:col-span-1 space-y-6">
              <div className="bg-white border border-emerald-200 rounded-2xl shadow-sm overflow-hidden h-full flex flex-col">
                <div className="bg-emerald-50 px-6 py-4 border-b border-emerald-200 flex justify-between items-center">
                  <h2 className="font-bold text-emerald-900 flex items-center gap-2"><ShieldCheck size={18}/> Validator Report</h2>
                  <span className="bg-emerald-600 text-white text-xs font-bold px-3 py-1 rounded-full">PASS</span>
                </div>
                <div className="p-6 space-y-4 flex-1">
                  <CheckItem text="Resource existence check" />
                  <CheckItem text="Hospital & ward consistency" />
                  <CheckItem text="Availability check (All free)" />
                  <CheckItem text="Compatibility check" />
                  <CheckItem text="Stale data check" />
                </div>
              </div>
            </div>

            <div className="xl:col-span-1 space-y-6">
              <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden flex flex-col h-full">
                <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
                  <h2 className="font-bold text-slate-800 flex items-center gap-2"><UserCheck size={18}/> Human Review</h2>
                </div>
                <div className="p-6 flex-1 flex flex-col">
                  <div className="space-y-3 mt-auto">
                    <button 
                      onClick={async () => {
                        try {
                          const result = await approveProposal(activeProposal.id);
                          alert(`Success! Allocation ID: ${result.allocation_id}\nOutcome: ${result.outcome}`);
                        } catch (e) {
                          alert("Error: Could not connect to FastAPI backend.");
                        }
                      }}
                      className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition-all shadow-md shadow-emerald-200 flex justify-center items-center gap-2"
                    >
                      <CheckCircle2 size={20} /> Approve & Reserve
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (activeTab === 'analysis') {
      return (
        <div className="space-y-6">
          <h1 className="text-2xl font-extrabold text-slate-900">System AI Analysis</h1>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 text-center">
            <BrainCircuit size={48} className="mx-auto text-blue-500 mb-4" />
            <h2 className="text-lg font-bold text-slate-800">AI Model Online</h2>
            <p className="text-slate-500 mt-2 max-w-lg mx-auto">Connected to NVIDIA Nemotron. The AI pipeline is ready to process new incidents. Submit a new incident to see the live extraction and planning process in action.</p>
          </div>
        </div>
      );
    }

    if (activeTab === 'inventory') {
      return (
        <div className="space-y-6">
          <h1 className="text-2xl font-extrabold text-slate-900">Resource Inventory</h1>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <table className="w-full text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-4 font-bold">Resource Type</th>
                  <th className="px-6 py-4 font-bold">Total</th>
                  <th className="px-6 py-4 font-bold">Available</th>
                  <th className="px-6 py-4 font-bold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-6 py-4 font-bold text-slate-800 flex items-center gap-2"><Bed size={18} className="text-blue-500"/> Beds</td>
                  <td className="px-6 py-4 text-slate-600">{loading ? '...' : totalBeds}</td>
                  <td className="px-6 py-4 font-bold text-emerald-600">{loading ? '...' : freeBeds}</td>
                  <td className="px-6 py-4"><span className="bg-emerald-100 text-emerald-700 px-2 py-1 rounded text-xs font-bold">Active</span></td>
                </tr>
                <tr>
                  <td className="px-6 py-4 font-bold text-slate-800 flex items-center gap-2"><UserCheck size={18} className="text-purple-500"/> Nurses</td>
                  <td className="px-6 py-4 text-slate-600">{loading ? '...' : totalNurses}</td>
                  <td className="px-6 py-4 font-bold text-emerald-600">{loading ? '...' : availableNurses}</td>
                  <td className="px-6 py-4"><span className="bg-emerald-100 text-emerald-700 px-2 py-1 rounded text-xs font-bold">Active</span></td>
                </tr>
                <tr>
                  <td className="px-6 py-4 font-bold text-slate-800 flex items-center gap-2"><Stethoscope size={18} className="text-rose-500"/> Doctors</td>
                  <td className="px-6 py-4 text-slate-600">{loading ? '...' : stateData?.doctors?.length || 0}</td>
                  <td className="px-6 py-4 font-bold text-emerald-600">{loading ? '...' : stateData?.doctors?.filter((d:any)=>d.available).length || 0}</td>
                  <td className="px-6 py-4"><span className="bg-emerald-100 text-emerald-700 px-2 py-1 rounded text-xs font-bold">Active</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    if (activeTab === 'validation') {
      return (
        <div className="space-y-6">
          <h1 className="text-2xl font-extrabold text-slate-900">Validation Reports</h1>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-8 text-center">
            <ShieldCheck size={48} className="mx-auto text-emerald-500 mb-4" />
            <h2 className="text-lg font-bold text-slate-800">Deterministic Validator</h2>
            <p className="text-slate-500 mt-2 max-w-lg mx-auto">The backend validator is running and enforcing safety rules. All AI proposals are automatically checked against PostgreSQL before human review.</p>
          </div>
        </div>
      );
    }

    if (activeTab === 'audit') {
      return (
        <div className="space-y-6">
          <h1 className="text-2xl font-extrabold text-slate-900">Audit Logs</h1>
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <table className="w-full text-left">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-4 font-bold">Time</th>
                  <th className="px-6 py-4 font-bold">Event</th>
                  <th className="px-6 py-4 font-bold">Actor</th>
                  <th className="px-6 py-4 font-bold">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-6 py-4 text-sm text-slate-600 flex items-center gap-2"><Clock size={14}/> Just now</td>
                  <td className="px-6 py-4 font-bold text-slate-800">System Startup</td>
                  <td className="px-6 py-4 text-slate-600">system</td>
                  <td className="px-6 py-4 text-slate-500 text-sm">FastAPI Backend Initialized</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="flex h-screen bg-slate-50 font-sans">
      <aside className="w-72 bg-slate-900 text-white flex flex-col shadow-2xl z-10">
        <div className="px-8 py-8 flex items-center gap-3 border-b border-slate-800">
          <div className="bg-emerald-500 p-2 rounded-lg text-white">
            <Activity size={24} strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="font-extrabold text-xl tracking-tight leading-tight">CrisisGuard AI</h1>
          </div>
        </div>
        
        <nav className="flex-1 py-6 space-y-1 overflow-y-auto px-4">
          <NavItem icon={<LayoutDashboard size={20}/>} label="Overview" active={activeTab === 'overview'} onClick={() => setActiveTab('overview')} />
          <NavItem icon={<AlertTriangle size={20}/>} label="New Incident" active={activeTab === 'incident'} onClick={() => setActiveTab('incident')} />
          <NavItem icon={<UserCheck size={20}/>} label="Human Review" active={activeTab === 'review'} onClick={() => setActiveTab('review')} badge={1} />
          <NavItem icon={<BrainCircuit size={20}/>} label="AI Analysis" active={activeTab === 'analysis'} onClick={() => setActiveTab('analysis')} />
          <NavItem icon={<Bed size={20}/>} label="Resource Inventory" active={activeTab === 'inventory'} onClick={() => setActiveTab('inventory')} />
          <NavItem icon={<ShieldCheck size={20}/>} label="Validation Reports" active={activeTab === 'validation'} onClick={() => setActiveTab('validation')} />
          <NavItem icon={<FileText size={20}/>} label="Audit Logs" active={activeTab === 'audit'} onClick={() => setActiveTab('audit')} />
        </nav>
      </aside>

      <main className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="bg-white border-b border-slate-200 h-20 px-8 flex items-center justify-between shadow-sm z-0">
          <div className="flex items-center gap-3 bg-slate-100 px-4 py-2.5 rounded-full w-96 border border-slate-200">
            <Search size={18} className="text-slate-400" />
            <input type="text" placeholder="Search..." className="bg-transparent border-none outline-none text-sm w-full text-slate-700 placeholder-slate-400 font-medium" />
          </div>
          <div className="flex items-center gap-6">
            <button className="text-slate-400 hover:text-slate-600 relative">
              <Bell size={22} />
            </button>
            <div className="flex items-center gap-3 border-l border-slate-200 pl-6">
              <div className="w-10 h-10 bg-slate-800 rounded-full flex items-center justify-center text-white font-bold"><User size={20}/></div>
              <div>
                <p className="text-sm font-bold text-slate-800">Dr. Ananya Sharma</p>
                <p className="text-xs text-slate-500 font-medium">Chief Reviewer</p>
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-8 bg-slate-50">
          {renderContent()}
        </div>
      </main>
    </div>
  );
}

function NavItem({ icon, label, active, onClick, badge }: { icon: React.ReactNode, label: string, active: boolean, onClick: () => void, badge?: number }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-4 px-4 py-3.5 rounded-xl transition-all duration-200 ${
        active ? 'bg-blue-600 text-white shadow-md font-bold' : 'text-slate-400 hover:text-white hover:bg-slate-800 font-medium'
      }`}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {badge && <span className="bg-rose-500 text-white text-xs px-2 py-0.5 rounded-full">{badge}</span>}
    </button>
  );
}

function StatCard({ title, value, total, icon, color, bg }: { title: string, value: string, total: string, icon: React.ReactNode, color: string, bg: string }) {
  return (
    <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 flex items-center justify-between">
      <div>
        <p className="text-sm font-bold text-slate-500 uppercase tracking-wide mb-1">{title}</p>
        <div className="flex items-baseline gap-1">
          <p className="text-3xl font-extrabold text-slate-900">{value}</p>
          {total && <p className="text-sm font-bold text-slate-400">/ {total}</p>}
        </div>
      </div>
      <div className={`p-4 rounded-2xl ${bg} ${color}`}>
        {icon}
      </div>
    </div>
  );
}

function CheckItem({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 text-sm font-semibold text-slate-700">
      <CheckCircle2 size={18} className="text-emerald-500 shrink-0" />
      {text}
    </div>
  );
}