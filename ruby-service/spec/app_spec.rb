RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end

    it 'returns 422 with validation errors' do
      error_obj = double(to_hash: { field: 'content', message: 'missing' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([error_obj])

      expect_any_instance_of(PolyglotAPI).not_to receive(:call_go_service)
      expect_any_instance_of(PolyglotAPI).not_to receive(:call_python_service)

      post '/analyze', { content: '', path: '' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Validation failed')
      expect(json['details']).to be_an(Array)
      expect(json['details'].first).to include('field' => 'content')
    end

    it 'passes detected language to python service based on file extension' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |val| val }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ["puts 'hi'"] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: "puts 'hi'"), anything)
        .and_return({ 'score' => 95.0, 'issues' => [] })

      post '/analyze', { content: "puts 'hi'", path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['summary']).to include('language' => 'ruby')
    end

    it 'accepts URL-encoded params when JSON body is invalid' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) { |val| val }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['line'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 80.0, 'issues' => [] })

      post '/analyze?content=puts+1&path=test.rb', 'invalid-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json).to have_key('summary')
      expect(json['summary']).to include('language' => 'ruby')
    end
  end

  describe 'GET /status' do
    it 'returns aggregated service statuses (healthy)' do
      allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
      allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']).to include('ruby', 'go', 'python')
      expect(json['services']['go']['status']).to eq('healthy')
      expect(json['services']['python']['status']).to eq('healthy')
    end

    it 'marks services unhealthy or unreachable on errors' do
      allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 500))
      allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_raise(Timeout::Error.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['go']['status']).to eq('unhealthy')
      expect(json['services']['python']['status']).to eq('unreachable')
      expect(json['services']['python']).to have_key('error')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when missing required params' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/Missing old_content or new_content/)
    end

    it 'returns diff and new code review for valid request' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(:old_content, :new_content))
        .and_return({ 'changes' => 3 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 88.5, 'issues' => [] })

      payload = { old_content: 'a', new_content: 'b' }
      post '/diff', payload.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']).to include('changes' => 3)
      expect(json['new_code_review']).to include('score' => 88.5)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/Missing content/)
    end

    it 'returns metrics, review, and clamped overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(:content))
        .and_return({ 'complexity' => 20 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(:content))
        .and_return({ 'score' => 50, 'issues' => Array.new(10, { 'type' => 'warn' }) })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to include('complexity' => 20)
      expect(json['review']).to include('score' => 50)
      expect(json['overall_quality']).to eq(0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/Missing files array/)
    end

    it 'returns aggregated dashboard stats with computed health score' do
      fixed_time = Time.utc(2023, 1, 1, 12, 0, 0)
      allow(Time).to receive(:now).and_return(fixed_time)

      file_stats = {
        'total_files' => 5,
        'total_lines' => 1000,
        'languages' => { 'ruby' => 5 }
      }
      review_stats = {
        'average_score' => 90.0,
        'total_issues' => 10,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(:files))
        .and_return(file_stats)
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(:files))
        .and_return(review_stats)

      files_payload = { files: [{ 'path' => 'a.rb', 'content' => 'puts 1' }] }
      post '/dashboard', files_payload.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['timestamp']).to eq(fixed_time.iso8601)
      expect(json['file_statistics']).to eq(file_stats)
      expect(json['review_statistics']).to eq(review_stats)
      expect(json['summary']['total_files']).to eq(5)
      expect(json['summary']['average_quality_score']).to eq(90.0)
      expect(json['summary']['health_score']).to eq(71.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with total count' do
      traces = [{ 'id' => 't1' }, { 'id' => 't2' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns traces for a given correlation id' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc123').and_return(['req1'])
      get '/traces/abc123'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('abc123')
      expect(json['trace_count']).to eq(1)
      expect(json['traces']).to eq(['req1'])
    end

    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('missing').and_return([])
      get '/traces/missing'
      expect(last_response.status).to eq(404)
      json = JSON.parse(last_response.body)
      expect(json['error']).to match(/No traces found/)
    end
  end

  describe 'validation errors management' do
    it 'GET /validation/errors returns collected errors' do
      errors = [{ 'field' => 'content', 'message' => 'required' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_errors']).to eq(1)
      expect(json['errors']).to eq(errors)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['message']).to eq('Validation errors cleared')
    end
  end
end
